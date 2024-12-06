import requests
import logging
import re
from typing import Dict, List, Optional
from unicodedata import normalize

logger = logging.getLogger(__name__)

class CapacitiesClient:
    def __init__(self, token: str, space_id: str):
        """
        Initialize the Capacities API client with improved error handling.
        
        Args:
            token: The API authentication token for Capacities
            space_id: The ID of the space where content will be saved
        """
        self.token = token
        self.space_id = space_id
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.base_url = "https://api.capacities.io"
        
    def _sanitize_text(self, text: Optional[str], max_length: int) -> Optional[str]:
        """
        Sanitizes and truncates text to ensure it's compatible with the API.
        Handles emoji, special characters, and ensures proper truncation.
        
        Args:
            text: The text to sanitize
            max_length: Maximum allowed length
        Returns:
            Sanitized text or None if input is None/empty
        """
        if not text:
            return None
            
        # Normalize unicode characters
        text = normalize('NFKC', text)
        
        # Remove or replace problematic characters
        text = re.sub(r'[\u0000-\u001F\u007F-\u009F]', '', text)  # Control characters
        
        # Handle emojis - either remove them or replace with text representation
        text = text.encode('ascii', 'ignore').decode('ascii')
        
        # Remove multiple spaces and trim
        text = ' '.join(text.split())
        
        return self._truncate_text(text, max_length)
        
    def _truncate_text(self, text: str, max_length: int) -> str:
        """
        Intelligently truncates text to the specified maximum length.
        """
        if not text or len(text) <= max_length:
            return text
            
        # Try to find the last sentence boundary within the limit
        truncated = text[:max_length]
        last_period = truncated.rfind('.')
        last_space = truncated.rfind(' ')
        
        # Prefer breaking at a sentence boundary, fall back to word boundary
        break_point = last_period if last_period > max_length * 0.7 else last_space
        if break_point != -1:
            truncated = truncated[:break_point + 1]
        else:
            truncated = truncated[:max_length - 1]
            
        return truncated.strip() + '...'

    def _sanitize_url(self, url: str) -> Optional[str]:
        """
        Validates and sanitizes URLs to ensure they're properly formatted.
        """
        if not url:
            return None
            
        # Ensure URL starts with http:// or https://
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        # Remove any whitespace
        url = url.strip()
        
        # Basic URL validation
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
            r'localhost|'  # localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
            
        return url if url_pattern.match(url) else None

    def _sanitize_tags(self, tags: Optional[List[str]]) -> List[str]:
        """
        Sanitizes tags to ensure they meet API requirements.
        """
        if not tags:
            return []
            
        sanitized_tags = []
        for tag in tags[:30]:  # Limit to 30 tags
            if not tag:
                continue
                
            # Remove special characters and spaces
            tag = re.sub(r'[^\w\s-]', '', tag)
            tag = tag.strip().lower()
            
            # Replace spaces with hyphens and remove multiple hyphens
            tag = re.sub(r'\s+', '-', tag)
            tag = re.sub(r'-+', '-', tag)
            
            if tag and len(tag) <= 50:  # Check if tag is not empty and not too long
                sanitized_tags.append(tag)
                
        return sanitized_tags

    def create_weblink(
        self,
        url: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
        author: Optional[str] = None
    ) -> Dict:
        """
        Creates a weblink in Capacities with improved error handling and content sanitization.
        
        Args:
            url: The URL to save
            title: Optional title override
            description: Optional description override
            tags: Optional list of tags
            notes: Optional markdown notes
            author: Optional author name
            
        Returns:
            API response as dictionary
            
        Raises:
            requests.exceptions.RequestException: If the API request fails
        """
        try:
            # Validate URL first
            sanitized_url = self._sanitize_url(url)
            if not sanitized_url:
                raise ValueError(f"Invalid URL format: {url}")

            # Build markdown content with proper sanitization
            md_parts = []
            if author:
                sanitized_author = self._sanitize_text(author, 100)
                if sanitized_author:
                    md_parts.append(f"**Autor:** {sanitized_author}")
            if notes:
                sanitized_notes = self._sanitize_text(notes, 200000)
                if sanitized_notes:
                    md_parts.append(sanitized_notes)
            md_text = "\n\n".join(md_parts) if md_parts else None

            # Prepare payload with sanitized content
            payload = {
                "spaceId": self.space_id,
                "url": sanitized_url
            }

            if title:
                sanitized_title = self._sanitize_text(title, 500)
                if sanitized_title:
                    payload["titleOverwrite"] = sanitized_title
                    
            if description:
                sanitized_desc = self._sanitize_text(description, 1000)
                if sanitized_desc:
                    payload["descriptionOverwrite"] = sanitized_desc
                    
            sanitized_tags = self._sanitize_tags(tags)
            if sanitized_tags:
                payload["tags"] = sanitized_tags
                
            if md_text:
                payload["mdText"] = md_text

            # Make the request with retry logic
            max_retries = 3
            retry_delay = 1
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    response = requests.post(
                        f"{self.base_url}/save-weblink",
                        headers=self.headers,
                        json=payload,
                        timeout=30  # Add timeout
                    )
                    
                    response.raise_for_status()
                    return response.json()
                    
                except requests.exceptions.RequestException as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        logger.warning(f"Attempt {attempt + 1} failed, retrying in {retry_delay} seconds...")
                        from time import sleep
                        sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                    continue
                    
            # If we get here, all retries failed
            error_msg = f"Failed to create weblink after {max_retries} attempts"
            if hasattr(last_error, 'response'):
                try:
                    error_detail = last_error.response.json()
                    error_msg += f" - Details: {error_detail}"
                except ValueError:
                    error_msg += f" - Raw response: {last_error.response.text}"
                    
            logger.error(error_msg)
            raise last_error

        except Exception as e:
            logger.error(f"Error creating weblink: {str(e)}")
            raise