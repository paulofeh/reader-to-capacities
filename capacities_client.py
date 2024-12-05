# capacities_client.py

import requests
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class CapacitiesClient:
    """
    Client for interacting with Capacities API, specifically focused on creating weblinks.
    The API uses a specific structure (MediaWebResource) for weblinks with predefined properties.
    """
    def __init__(self, token: str, space_id: str):
        self.token = token
        self.space_id = space_id
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.base_url = "https://api.capacities.io"

    def create_weblink(self, url: str, title: Optional[str] = None, description: Optional[str] = None, 
                  tags: Optional[List[str]] = None, notes: Optional[str] = None, author: Optional[str] = None) -> Dict:
        """
        Creates a weblink in Capacities using the /save-weblink endpoint.
        
        Args:
            url: The URL of the weblink
            title: Optional custom title (max 500 chars)
            description: Optional custom description (max 1000 chars)
            tags: Optional list of tags (max 30 tags)
            notes: Optional markdown text for notes (max 200000 chars)
            author: Optional author name to be included in markdown text
        """
        try:
            md_parts = []
            if author:
                md_parts.append(f"**Autor:** {author}")
            if notes:
                md_parts.append(notes)
                
            md_text = "\n\n".join(md_parts) if md_parts else None

            payload = {
                "spaceId": self.space_id,
                "url": url,
            }

            if title:
                payload["titleOverwrite"] = title[:500]
            if description:
                payload["descriptionOverwrite"] = description[:1000]
            if tags:
                payload["tags"] = tags[:30]
            if md_text:
                payload["mdText"] = md_text[:200000]

            response = requests.post(
                f"{self.base_url}/save-weblink",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            
            if not response.ok:
                error_detail = response.json().get('detail', 'No error detail provided')
                logger.error(f"API Error: {error_detail}")
                
            return response.json()
                
        except requests.exceptions.RequestException as e:
            error_detail = e.response.json() if hasattr(e, 'response') else str(e)
            logger.error(f"Failed to create weblink in Capacities: {error_detail}")
            raise