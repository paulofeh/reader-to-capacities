import requests
import logging
from datetime import datetime
from time import sleep
from typing import Optional, Dict, List
from capacities_client import CapacitiesClient

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

def process_article_url(article: Dict) -> Optional[str]:
    """Returns the most appropriate URL for the article based on its type."""
    source_url = article.get("source_url")
    url = article.get("url")
    
    if source_url and "youtube.com" in source_url:
        return source_url
    
    return source_url if source_url else url

def clean_youtube_title(title: str) -> str:
    """Formats YouTube-style titles to be more readable."""
    if "|" in title:
        parts = [part.strip() for part in title.split("|")]
        parts[0] = parts[0].title()
        return ": ".join(parts)
    return title

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
        logger.info(f"Processing {len(articles_to_process)} articles")

        processed_count = 0
        for article in articles_to_process:
            if article["id"] in processed_ids:
                continue
                
            title = article["title"]
            url = process_article_url(article)
            if not url:
                continue
                
            if "youtube.com" in url:
                title = clean_youtube_title(title)
                
            highlights = readwise_client.get_highlights_for_article(article["id"])
            formatted_highlights = readwise_client.format_highlights_markdown(highlights)
            
            notes_parts = []
            if article.get("reading_progress"):
                notes_parts.append(f"**Reading Progress:** {article['reading_progress'] * 100:.1f}%")
            if article.get("notes"):
                notes_parts.append("\n## Notes")
                notes_parts.append(article["notes"])
            if formatted_highlights:
                notes_parts.append("\n" + formatted_highlights)
                
            tags = list(article.get('tags', []))
            if DEFAULT_TAGS:
                tags.extend(DEFAULT_TAGS)

            try:
                created_weblink = capacities_client.create_weblink(
                    url=url,
                    title=title,
                    description=article.get("summary", ""),
                    notes="\n\n".join(notes_parts) if notes_parts else None,
                    author=article.get("author", "Unknown"),
                    tags=tags
                )
                
                processed_count += 1
                logger.info(f"Created weblink ({processed_count}/{len(articles_to_process)}): {title}")
                add_processed_id(article["id"])
                
            except ValueError as e:
                # Handle validation errors (bad URLs, etc.)
                logger.warning(f"Validation error for '{title}': {e}")
                continue
            except requests.exceptions.RequestException as e:
                # Handle API errors
                logger.error(f"API error for '{title}': {e}")
                continue
            except Exception as e:
                # Handle unexpected errors
                logger.error(f"Unexpected error for '{title}': {e}")
                continue
        
        logger.info(f"Processing completed. Created {processed_count} new weblinks.")
        
    except Exception as e:
        logger.error(f"Script failed: {e}")

if __name__ == "__main__":
    main()