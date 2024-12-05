# capacities_client.py

import requests
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class CapacitiesClient:
    def __init__(self, token: str, space_id: str):
        """
        Initialize the Capacities API client.
        
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
        
    def _truncate_text(self, text: str, max_length: int) -> str:
        """
        Intelligently truncates text to the specified maximum length.
        If truncation is needed, it adds an ellipsis and tries to break at a sentence or word boundary.
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
        Creates a weblink in Capacities with proper content length handling.
        """
        try:
            # Build markdown content
            md_parts = []
            if author:
                md_parts.append(f"**Autor:** {author}")
            if notes:
                md_parts.append(notes)
            md_text = "\n\n".join(md_parts) if md_parts else None

            # Prepare payload with proper length constraints
            payload = {
                "spaceId": self.space_id,
                "url": url,
            }

            if title:
                payload["titleOverwrite"] = self._truncate_text(title, 500)
            if description:
                payload["descriptionOverwrite"] = self._truncate_text(description, 1000)
            if tags:
                payload["tags"] = tags[:30]
            if md_text:
                payload["mdText"] = self._truncate_text(md_text, 200000)

            # Make the request
            response = requests.post(
                f"{self.base_url}/save-weblink",
                headers=self.headers,
                json=payload
            )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            error_msg = f"Failed to create weblink: {str(e)}"
            if hasattr(e, 'response'):
                try:
                    error_detail = e.response.json()
                    error_msg += f" - Details: {error_detail}"
                except ValueError:
                    error_msg += f" - Raw response: {e.response.text}"
            logger.error(error_msg)
            raise