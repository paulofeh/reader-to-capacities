import requests
import logging
import re
from typing import Dict, List, Optional, Union
from unicodedata import normalize
from time import sleep
from datetime import datetime

logger = logging.getLogger(__name__)

class CapacitiesClient:
    """
    Client for interacting with the Capacities API with improved handling for various content types
    and robust error management.
    """
    
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
        
        # Rate limiting settings
        self.min_request_interval = 1.0  # Minimum seconds between requests
        self.last_request_time = 0.0
        
    def _wait_for_rate_limit(self):
        """
        Ensures proper spacing between API requests to avoid rate limiting.
        """
        current_time = datetime.now().timestamp()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            sleep(self.min_request_interval - time_since_last)
        self.last_request_time = datetime.now().timestamp()
        
    def _sanitize_text(self, text: Optional[str], max_length: int) -> Optional[str]:
        """
        Sanitizes and truncates text while preserving accented characters.
        
        Args:
            text: The text to sanitize
            max_length: Maximum allowed length
        Returns:
            Sanitized text or None if input is None/empty
        """
        if not text:
            return None
            
        # Normalize unicode characters (this standardizes the representation
        # but preserves the actual characters)
        text = normalize('NFKC', text)
        
        # Remove only control characters while preserving everything else
        text = re.sub(r'[\u0000-\u0008\u000B-\u000C\u000E-\u001F\u007F]', '', text)
        
        # Preserve markdown formatting while removing multiple spaces
        lines = text.split('\n')
        cleaned_lines = [' '.join(line.split()) for line in lines]
        text = '\n'.join(cleaned_lines)
        
        return self._truncate_text(text, max_length)
        
    def _truncate_text(self, text: str, max_length: int) -> str:
        """
        Intelligently truncates text while preserving markdown formatting.
        """
        if not text or len(text) <= max_length:
            return text
            
        # Try to find break points that don't disrupt markdown
        truncated = text[:max_length]
        
        # Look for appropriate break points
        break_candidates = [
            truncated.rfind('\n\n'),  # Paragraph break
            truncated.rfind('.  '),   # Sentence break with double space
            truncated.rfind('. '),    # Sentence break
            truncated.rfind('\n'),    # Line break
            truncated.rfind('. '),    # Regular sentence
            truncated.rfind(' ')      # Word break
        ]
        
        # Use the first valid break point that's not too close to the start
        min_length = max_length * 0.7
        for break_point in break_candidates:
            if break_point > min_length:
                truncated = truncated[:break_point + 1]
                break
        else:
            truncated = truncated[:max_length - 3]
            
        return truncated.strip() + '...'

    def _sanitize_url(self, url: str, allow_readwise: bool = True) -> Optional[str]:
        """
        Validates and sanitizes URLs with special handling for Readwise URLs.
        
        Args:
            url: The URL to sanitize
            allow_readwise: Whether to allow Readwise-specific URLs
        Returns:
            Sanitized URL or None if invalid
        """
        if not url:
            return None
            
        # Special handling for Readwise URLs if allowed
        if allow_readwise and 'readwise.io' in url:
            if url.startswith(('http://', 'https://')):
                return url
            return f'https://readwise.io{url if url.startswith("/") else f"/{url}"}'
            
        # Handle regular URLs
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        url = url.strip()
        
        # Enhanced URL validation pattern
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
            r'localhost|'  # localhost
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP address
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?][^\s]*)?$',  # path and query
            re.IGNORECASE)
            
        return url if url_pattern.match(url) else None

    def _sanitize_tags(self, tags: Optional[List[str]]) -> List[str]:
        """
        Sanitizes tags with improved handling of special characters and categories.
        """
        if not tags:
            return []
            
        sanitized_tags = []
        for tag in tags[:30]:  # Limit to 30 tags
            if not tag:
                continue
                
            # Convert to lowercase and remove special characters
            tag = tag.lower().strip()
            tag = re.sub(r'[^\w\s-]', '', tag)
            
            # Handle spaces and hyphens
            tag = re.sub(r'\s+', '-', tag)
            tag = re.sub(r'-+', '-', tag)
            
            if tag and len(tag) <= 50:
                sanitized_tags.append(tag)
                
        return list(set(sanitized_tags))  # Remove duplicates

    def create_weblink(
        self,
        url: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
        author: Optional[str] = None,
        content_type: Optional[str] = None
    ) -> Dict:
        """
        Creates a weblink in Capacities with comprehensive error handling and content type support.
        
        Args:
            url: The URL to save
            title: Optional title override
            description: Optional description override
            tags: Optional list of tags
            notes: Optional markdown notes
            author: Optional author name
            content_type: Optional content type (e.g., 'email', 'article', 'youtube')
            
        Returns:
            API response as dictionary
            
        Raises:
            ValueError: If URL is invalid or required fields are missing
            requests.exceptions.RequestException: If the API request fails
        """
        try:
            # Validate URL with special handling for content types
            allow_readwise = content_type == 'email'
            sanitized_url = self._sanitize_url(url, allow_readwise=allow_readwise)
            if not sanitized_url:
                raise ValueError(f"Invalid URL format: {url}")

            # Prepare markdown content
            md_parts = []
            if author:
                sanitized_author = self._sanitize_text(author, 100)
                if sanitized_author:
                    prefix = "From" if content_type == 'email' else "Author"
                    md_parts.append(f"**{prefix}:** {sanitized_author}")
                    
            if content_type:
                md_parts.append(f"**Type:** {content_type.title()}")
                
            if notes:
                sanitized_notes = self._sanitize_text(notes, 200000)
                if sanitized_notes:
                    md_parts.append(sanitized_notes)
                    
            md_text = "\n\n".join(md_parts) if md_parts else None

            # Prepare the API payload
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
                    
            # Add content type to tags if provided
            if content_type:
                tags = tags or []
                tags.append(content_type)
            sanitized_tags = self._sanitize_tags(tags)
            if sanitized_tags:
                payload["tags"] = sanitized_tags
                
            if md_text:
                payload["mdText"] = md_text

            # Make request with improved retry logic
            max_retries = 3
            retry_delay = 1
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    self._wait_for_rate_limit()
                    
                    response = requests.post(
                        f"{self.base_url}/save-weblink",
                        headers=self.headers,
                        json=payload,
                        timeout=30
                    )
                    
                    response.raise_for_status()
                    return response.json()
                    
                except requests.exceptions.RequestException as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"Attempt {attempt + 1} failed for '{title}', "
                            f"retrying in {retry_delay} seconds..."
                        )
                        sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                    continue
                    
            # Handle final error after all retries
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