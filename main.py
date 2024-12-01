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

    def get_articles_with_highlights(self, updated_after: Optional[str] = None, limit: Optional[int] = None) -> List[Dict]:
        """
        Fetches articles from the archive in Readwise Reader.
        
        This method specifically targets archived articles, which represent content that
        has been processed and deemed worthy of keeping. The archive status serves as
        a deliberate signal that the content should be included in the PKM system.
        
        Args:
            updated_after: Optional timestamp to fetch articles updated after this date
            limit: Optional maximum number of articles to return
            
        Returns:
            A list of archived articles, potentially limited to a specified count
        """
        all_articles = []
        next_page_cursor = None
        total_fetched = 0

        while True:
            # Include the location parameter to filter for archived items
            params = {
                "withHtmlContent": "false",
                "location": "archive"  # This replaces our previous reading_progress filter
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
                
                # We no longer need to filter by reading_progress since we're
                # already getting archived articles
                if articles:
                    # If we have a limit, only take what we need
                    if limit:
                        remaining = limit - total_fetched
                        articles = articles[:remaining]
                    
                    all_articles.extend(articles)
                    total_fetched += len(articles)
                    logger.info(f"Fetched {len(articles)} archived articles (Total: {total_fetched})")
                    
                    # Check if we've reached our limit
                    if limit and total_fetched >= limit:
                        logger.info(f"Reached article limit of {limit}")
                        break

                next_page_cursor = data.get("nextPageCursor")
                if not next_page_cursor:
                    break

            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                break

        logger.info(f"Completed fetching {total_fetched} total archived articles")
        return all_articles
    
    def get_highlights_for_article(self, article_id: str) -> List[Dict]:
        """
        Fetches all highlights for a specific article.
        
        This method queries the Readwise API to get all highlights associated with
        the given article ID. It handles pagination and ensures we stay within
        rate limits while fetching the highlights.
        
        Args:
            article_id: The unique identifier of the article in Readwise
            
        Returns:
            A list of highlights, each containing the highlighted text and any notes
        """
        highlights = []
        params = {
            "withHtmlContent": "false",
            "category": "highlight",  # We only want highlights
        }

        try:
            # Make the API request with proper rate limiting
            self._wait_for_rate_limit()
            response = requests.get(
                READWISE_LIST_URL,
                headers=self.headers,
                params=params
            )
            response.raise_for_status()
            data = response.json()

            # Filter highlights for our specific article
            article_highlights = [
                highlight for highlight in data.get("results", [])
                if highlight.get("parent_id") == article_id
            ]

            if article_highlights:
                highlights.extend(article_highlights)
                logger.info(f"Found {len(article_highlights)} highlights for article")

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

        formatted_parts = ["## Anotações"]
        
        for highlight in highlights:
            # Get the highlighted text from the 'content' field
            highlighted_text = highlight.get('content', '').strip()
            if highlighted_text:
                # Add the highlighted text with a bullet point
                formatted_parts.append(f"\n* {highlighted_text}")
                
                # If there's a note associated with the highlight, add it indented
                note = highlight.get('notes', '').strip()
                if note:
                    formatted_parts.append(f"  \n  *Nota: {note}*")

        return "\n".join(formatted_parts)
        
def process_article_url(article: Dict) -> Optional[str]:
    """
    Process the article URL based on its category and source.
    Returns a valid URL or None if no valid URL can be created.
    """
    category = article.get("category", "").lower()
    source_url = article.get("source_url")
    url = article.get("url")
    
    if category == "email":
        # For email newsletters, we'll use the Readwise reader URL as a fallback
        return url if url else None
    else:
        # For web articles, prefer the original source URL
        return source_url if source_url else url

def main():
    """
    Main function to orchestrate the article fetching and creation process.
    Only processes articles that have been updated after our reference date,
    focusing on archived items that represent completed reading.
    """
    readwise_client = ReadwiseClient(READWISE_TOKEN)
    capacities_client = CapacitiesClient(CAPACITIES_TOKEN, CAPACITIES_SPACE_ID)
    processed_ids = get_processed_ids()
    
    try:
        # Get the reference timestamp for filtering
        reference_timestamp = get_reference_timestamp()
        logger.info(f"Fetching articles updated after: {ARTICLES_UPDATED_AFTER}")
        
        # Include the timestamp in our article fetch
        articles = readwise_client.get_articles_with_highlights(
            updated_after=reference_timestamp,
            limit=ARTICLES_PER_RUN
        )
        
        logger.info(
            f"Found {len(articles)} articles to process "
            f"(limited to {ARTICLES_PER_RUN} per run, "
            f"updated after {ARTICLES_UPDATED_AFTER})"
        )

        articles = readwise_client.get_articles_with_highlights(limit=ARTICLES_PER_RUN)
        logger.info(f"Found {len(articles)} articles to process (limited to {ARTICLES_PER_RUN} per run)")
        
        processed_count = 0
        for article in articles:
            article_id = article["id"]
            
            if article_id in processed_ids:
                continue
            
            # Extract all article information in one place for clarity
            title = article["title"]
            url = process_article_url(article)
            description = article.get("summary", "")  # Now properly defined
            author = article.get("author", "Unknown")  # Now properly defined with default value
            
            if not url:
                logger.warning(f"Skipping article without valid URL: {title}")
                continue
            
            # Fetch highlights for this article
            highlights = readwise_client.get_highlights_for_article(article_id)
            formatted_highlights = readwise_client.format_highlights_markdown(highlights)
            
            # Prepare notes content with all sections
            notes_parts = []
                        
            # Add original article notes
            if article.get("notes"):
                notes_parts.append("\n## Comentários")
                notes_parts.append(article["notes"])
            
            # Add highlights
            if formatted_highlights:
                notes_parts.append("\n" + formatted_highlights)
            
            notes = "\n\n".join(notes_parts) if notes_parts else None
            
            try:
                # Create the weblink in Capacities
                created_weblink = capacities_client.create_weblink(
                    url=url,
                    title=title,
                    description=description,
                    notes=notes,
                    author=author
                )
                
                processed_count += 1
                logger.info(f"Created weblink in Capacities ({processed_count}/{len(articles)}): {title}")
                logger.info(f"  - Included {len(highlights)} highlights")
                
                add_processed_id(article_id)
                
            except Exception as e:
                logger.error(f"Failed to create weblink for '{title}': {e}")
                continue

        logger.info(f"Processing completed successfully. Created {processed_count} new weblinks.")
        
    except Exception as e:
        logger.error(f"Script failed: {e}")

if __name__ == "__main__":
    main()