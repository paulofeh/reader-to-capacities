import requests
import logging
from datetime import datetime, timezone
from time import sleep
from typing import Optional, Dict, List
from capacities_client import CapacitiesClient
from pathlib import Path

from config import (
    READWISE_TOKEN,
    READWISE_LIST_URL,
    CAPACITIES_TOKEN,
    CAPACITIES_SPACE_ID,
    ARTICLES_PER_RUN,
    ARTICLES_UPDATED_AFTER,
    DEFAULT_TAGS,
    get_processed_ids,
    add_processed_id,
    get_reference_timestamp
)

# Set up logging to help us track what's happening when the script runs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

import requests
import logging
from datetime import datetime, timezone
from time import sleep
from typing import Optional, Dict, List

from config import (
    READWISE_TOKEN,
    READWISE_LIST_URL,
    get_processed_ids,
    add_processed_id
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ReadwiseClient:
    """Handles interactions with the Readwise Reader API with improved rate limiting."""
    def __init__(self, token: str):
        self.token = token
        self.headers = {"Authorization": f"Token {token}"}
        self.last_request_time = 0
        self.request_count = 0
        self.window_start = datetime.now().timestamp()
        
        # Rate limiting settings
        self.requests_per_minute = 15  # Setting lower than the 20/min limit for safety
        self.min_request_interval = 3  # Minimum seconds between requests

    def _wait_for_rate_limit(self):
        """Enhanced rate limiting with rolling window."""
        current_time = datetime.now().timestamp()
        
        # Enforce minimum interval between requests
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_interval:
            sleep(self.min_request_interval - time_since_last_request)
        
        # Check rolling window
        window_elapsed = current_time - self.window_start
        if window_elapsed >= 60:  # Reset window after a minute
            self.request_count = 0
            self.window_start = current_time
        elif self.request_count >= self.requests_per_minute:
            # Wait for the remainder of the minute
            sleep(60 - window_elapsed)
            self.request_count = 0
            self.window_start = datetime.now().timestamp()
        
        self.request_count += 1
        self.last_request_time = datetime.now().timestamp()

    def _make_request(self, params: Dict) -> Dict:
        """Make a request with retry logic for rate limits."""
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                self._wait_for_rate_limit()
                response = requests.get(
                    READWISE_LIST_URL,
                    headers=self.headers,
                    params=params
                )
                response.raise_for_status()
                return response.json()
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:  # Rate limit exceeded
                    retry_after = int(e.response.headers.get('Retry-After', retry_delay))
                    logger.warning(f"Rate limit hit, waiting {retry_after} seconds...")
                    sleep(retry_after)
                    continue
                else:
                    raise
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed: {e}")
                if attempt == max_retries - 1:
                    raise
                sleep(retry_delay)
                
        return {}  # Return empty dict if all retries failed

    def get_articles_with_highlights(self, updated_after: Optional[str] = None, processed_ids: Optional[set] = None) -> List[Dict]:
        """
        Fetches articles from the archive in Readwise Reader that haven't been processed yet.
        
        This method retrieves all archived articles updated after a certain date and filters out
        those that have already been processed. This ensures we're always working with new content
        rather than potentially re-examining already processed articles.
        
        Args:
            updated_after: Optional timestamp to fetch articles updated after this date
            processed_ids: Set of article IDs that have already been processed
            
        Returns:
            A list of unprocessed archived articles
        """
        all_articles = []
        next_page_cursor = None
        total_fetched = 0
        processed_ids = processed_ids or set()

        while True:
            params = {
                "withHtmlContent": "false",
                "location": "archive"
            }
            
            if next_page_cursor:
                params["pageCursor"] = next_page_cursor
            if updated_after:
                params["updatedAfter"] = updated_after

            try:
                data = self._make_request(params)
                
                if not data:  # Empty response after retries
                    break

                articles = data.get("results", [])
                
                # Filter for unprocessed articles
                new_articles = [
                    {
                        **article,
                        'tags': article.get('tags', {}).keys()  # Convert tags dict to list
                    }
                    for article in articles
                    if article["id"] not in processed_ids
                ]
                
                if new_articles:
                    all_articles.extend(new_articles)
                    total_fetched += len(new_articles)
                    logger.info(f"Fetched {len(new_articles)} new archived articles (Total unprocessed: {total_fetched})")

                next_page_cursor = data.get("nextPageCursor")
                if not next_page_cursor:
                    break

            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                break

        logger.info(f"Completed fetching {total_fetched} total unprocessed archived articles")
        return all_articles
    
    def get_highlights_for_article(self, article_id: str) -> List[Dict]:
        highlights = []
        params = {
            "withHtmlContent": "false",
            "category": "highlight",
        }

        try:
            self._wait_for_rate_limit()
            response = requests.get(
                READWISE_LIST_URL,
                headers=self.headers,
                params=params
            )
            response.raise_for_status()
            data = response.json()

            # Filter highlights and sort by creation date
            article_highlights = [
                highlight for highlight in data.get("results", [])
                if highlight.get("parent_id") == article_id
            ]
            
            if article_highlights:
                # Sort by created_at timestamp
                sorted_highlights = sorted(article_highlights, key=lambda x: x.get('created_at', ''))
                highlights.extend(sorted_highlights)
                logger.info(f"Found {len(sorted_highlights)} highlights for article")

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch highlights: {e}")

        return highlights

    def format_highlights_markdown(self, highlights: List[Dict]) -> str:
        """
        Formats the highlights into a readable markdown format.
        
        This method takes raw highlight data and converts it into a well-structured
        markdown format for Capacities. It includes both the highlighted text and any
        associated notes.
        
        Args:
            highlights: List of highlight dictionaries from the API
            
        Returns:
            A formatted markdown string containing all highlights
        """
        if not highlights:
            return ""
            
        # Sort highlights by position (chronological order)
        sorted_highlights = sorted(highlights, key=lambda x: x.get('position', 0))
        
        formatted_parts = ["## Anotações"]
        
        for highlight in sorted_highlights:
            highlighted_text = highlight.get('content', '').strip()
            if highlighted_text:
                formatted_parts.append(f"\n* {highlighted_text}")
                note = highlight.get('notes', '').strip()
                if note:
                    formatted_parts.append(f"  \n  *Nota: {note}*")

        return "\n".join(formatted_parts)
        
def process_article_url(article: Dict) -> Optional[str]:
    """
    Process the article URL based on its category and source.
    Returns a valid URL or None if no valid URL can be created.
    
    This function handles different types of content, including YouTube videos,
    email newsletters, and web articles. For YouTube videos, it ensures we're
    using the original source URL since the Readwise reader URL won't work
    properly with the Capacities API.
    """
    category = article.get("category", "").lower()
    source_url = article.get("source_url")
    url = article.get("url")
    
    # Check if this is a YouTube video by examining the source URL
    if source_url and "youtube.com" in source_url:
        # Always use the original YouTube URL for videos
        return source_url
    
    if category == "email":
        # For email newsletters, use the Readwise reader URL as a fallback
        return url if url else None
    else:
        # For web articles, prefer the original source URL
        return source_url if source_url else url
    
def clean_youtube_title(title: str) -> str:
    """
    Cleans YouTube-style titles by removing common patterns and making them
    more readable in Capacities.
    
    For example, transforms:
    "MELHORES PREDIOS | Something else" into "Melhores Predios: Something else"
    """
    if "|" in title:
        # Split on the vertical bar and clean up each part
        parts = [part.strip() for part in title.split("|")]
        # Convert the first part from uppercase to title case
        parts[0] = parts[0].title()
        # Join with a colon instead of the vertical bar
        return ": ".join(parts)
    return title

# In main(), before creating the weblink:
if "youtube.com" in url:
    title = clean_youtube_title(title)

def main():
    """
    Main function to orchestrate the article fetching and creation process.
    This function coordinates the entire workflow of fetching articles from Readwise Reader
    and creating corresponding weblinks in Capacities, while maintaining processing history
    and handling errors appropriately.
    """
    # Initialize our API clients
    readwise_client = ReadwiseClient(READWISE_TOKEN)
    capacities_client = CapacitiesClient(CAPACITIES_TOKEN, CAPACITIES_SPACE_ID)
    
    # Get our record of previously processed articles
    processed_ids = get_processed_ids()
    
    try:
        # Get our reference timestamp for filtering articles
        reference_timestamp = get_reference_timestamp()
        logger.info(f"Fetching articles updated after: {ARTICLES_UPDATED_AFTER}")
        
        # Fetch all unprocessed articles that were updated after our reference date
        all_unprocessed_articles = readwise_client.get_articles_with_highlights(
            updated_after=reference_timestamp,
            processed_ids=processed_ids
        )
        
        # Take only the first batch of articles according to our per-run limit
        articles_to_process = all_unprocessed_articles[:ARTICLES_PER_RUN]
        
        logger.info(
            f"Found {len(all_unprocessed_articles)} unprocessed articles "
            f"(processing {len(articles_to_process)} this run)"
        )
        
        processed_count = 0
        for article in articles_to_process:
            article_id = article["id"]
            
            # Double-check we haven't processed this article before
            if article_id in processed_ids:
                continue
            
            # Extract all relevant article information
            title = article["title"]
            url = process_article_url(article)
            description = article.get("summary", "")
            author = article.get("author", "Unknown")

            # Cleans up youtube titles            
            if "youtube.com" in url:
                title = clean_youtube_title(title)

            # Skip articles without a valid URL
            if not url:
                logger.warning(f"Skipping article without valid URL: {title}")
                continue
            
            # Fetch highlights for this specific article
            highlights = readwise_client.get_highlights_for_article(article_id)
            formatted_highlights = readwise_client.format_highlights_markdown(highlights)
            
            # Prepare the complete notes content with all available information
            notes_parts = []
            
            # Add reading progress if available
            if article.get("reading_progress"):
                notes_parts.append(
                    f"**Reading Progress:** {article['reading_progress'] * 100:.1f}%"
                )
            
            # Add original article notes if present
            if article.get("notes"):
                notes_parts.append("\n## Notes")
                notes_parts.append(article["notes"])
            
            # Add formatted highlights if we found any
            if formatted_highlights:
                notes_parts.append("\n" + formatted_highlights)
            
            # Combine all notes parts or set to None if empty
            notes = "\n\n".join(notes_parts) if notes_parts else None
            
            try:
                # Create the weblink in Capacities
                tags = list(article.get('tags', []))  # Add this
                if DEFAULT_TAGS:                      # Add this
                    tags.extend(DEFAULT_TAGS)         # Add this

                created_weblink = capacities_client.create_weblink(
                    url=url,
                    title=title,
                    description=description,
                    notes=notes,
                    author=author,
                    tags=tags  # Update this line
                )
                
                processed_count += 1
                logger.info(f"Created weblink in Capacities ({processed_count}/{len(articles_to_process)}): {title}")
                if highlights:
                    logger.info(f"  - Included {len(highlights)} highlights")
                
                # Mark as processed only after successful creation
                add_processed_id(article_id)
                
            except Exception as e:
                logger.error(f"Failed to create weblink for '{title}': {e}")
                continue
        
        # Log final processing summary
        logger.info(
            f"Processing completed successfully. Created {processed_count} new weblinks. "
            f"{len(all_unprocessed_articles) - len(articles_to_process)} articles remaining."
        )
        
    except Exception as e:
        logger.error(f"Script failed: {e}")

if __name__ == "__main__":
    main()