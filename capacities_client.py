# capacities_client.py

import requests
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class CapacitiesClient:
    def __init__(self, token: str, space_id: str):
        self.token = token
        self.space_id = space_id
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.base_url = "https://api.capacities.io"

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
        Creates a weblink in Capacities with enhanced handling for different content types.
        """
        try:
            # Build markdown content
            md_parts = []
            if author:
                md_parts.append(f"**Autor:** {author}")
            if notes:
                md_parts.append(notes)
            md_text = "\n\n".join(md_parts) if md_parts else None

            # Base payload
            payload = {
                "spaceId": self.space_id,
                "url": url,
            }

            # Handle YouTube videos differently
            if "youtube.com" in url or "youtu.be" in url:
                # For YouTube videos, we might need to set a specific category
                payload["category"] = "video"  # If Capacities API supports this

            # Add optional fields
            if title:
                payload["titleOverwrite"] = title[:500]
            if description:
                payload["descriptionOverwrite"] = description[:1000]
            if tags:
                payload["tags"] = tags[:30]
            if md_text:
                payload["mdText"] = md_text[:200000]

            # Log the request details for debugging
            logger.debug(f"Sending request to {self.base_url}/save-weblink")
            logger.debug(f"Headers: {self.headers}")
            logger.debug(f"Payload: {payload}")

            # Make the request
            response = requests.post(
                f"{self.base_url}/save-weblink",
                headers=self.headers,
                json=payload
            )

            # Log the response for debugging
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response content: {response.text}")

            # Check if response is valid JSON
            try:
                response_data = response.json()
            except ValueError as json_err:
                logger.error(f"Invalid JSON response: {response.text}")
                raise ValueError(f"API returned invalid JSON: {response.text}")

            response.raise_for_status()
            return response_data

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