import requests
import logging
from datetime import datetime, timezone
from time import sleep
from typing import Optional, Dict, List, Tuple
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

def process_article_url(article: Dict) -> Tuple[Optional[str], bool]:
    """
    Returns the most appropriate URL for the article and whether it's a forwarded email.
    
    Args:
        article: Article dictionary from Readwise API
        
    Returns:
        Tuple of (processed_url, is_email) where:
            - processed_url is either a valid URL or None if article should be skipped
            - is_email is True if the content is from an email/newsletter
    """
    source_url = article.get("source_url")
    url = article.get("url", "")
    category = article.get("category", "").lower()
    
    # Handle email content
    if (category == "email" or 
        "reader-forwarded-email" in url or 
        url.startswith("mailto:") or
        (source_url and "reader-forwarded-email" in source_url)):
        
        # For email content, we'll create a special URL using the article ID
        # This ensures a unique identifier while making it clear it's email content
        email_url = f"https://readwise.io/reader/document/{article['id']}"
        return email_url, True
    
    # Handle YouTube content
    if source_url and "youtube.com" in source_url:
        return source_url, False
    
    # For regular articles, prefer source_url if available
    final_url = source_url if source_url else url
    
    # Skip if no valid URL is found
    if not final_url or final_url.startswith("mailto:"):
        logger.warning(f"No valid URL found for article: {article.get('title', 'Unknown')}")
        return None, False
        
    return final_url, False

def verify_article_date(article: Dict, reference_date: str) -> bool:
    """
    Verifies if an article should be processed based on its date.
    
    Args:
        article: Article dictionary from Readwise API
        reference_date: ISO format date string to compare against
        
    Returns:
        Boolean indicating if article should be processed
    """
    try:
        # Convert reference date string to datetime
        ref_date = datetime.fromisoformat(reference_date.replace('Z', '+00:00'))
        
        # Get article's relevant dates
        updated_at = article.get("updated_at")
        created_at = article.get("created_at")
        saved_at = article.get("saved_at")
        
        # Convert to datetime objects, handling potential None values
        dates_to_check = []
        for date_str in [updated_at, created_at, saved_at]:
            if date_str:
                try:
                    dates_to_check.append(
                        datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    )
                except ValueError:
                    continue
        
        if not dates_to_check:
            logger.warning(f"No valid dates found for article: {article.get('title', 'Unknown')}")
            return False
            
        # Use the most recent date for comparison
        most_recent_date = max(dates_to_check)
        
        # Article should be processed if its most recent date is after the reference date
        return most_recent_date > ref_date
        
    except (ValueError, AttributeError) as e:
        logger.error(f"Error processing dates for article {article.get('title', 'Unknown')}: {e}")
        return False
    
def format_email_content(article: Dict, highlights: list) -> str:
    """
    Formats email content with special handling for newsletters and forwarded emails.
    
    Args:
        article: Article dictionary from Readwise API
        highlights: List of highlights for the article
        
    Returns:
        Formatted markdown string for email content
    """
    parts = []
    
    # Add email-specific metadata
    if article.get("author"):
        parts.append(f"**From:** {article['author']}")
    
    if article.get("published_date"):
        parts.append(f"**Date:** {article['published_date']}")
        
    if article.get("category") == "email":
        parts.append("**Type:** Newsletter/Email")
        
    # Add summary if available
    if article.get("summary"):
        parts.append("\n## Summary")
        parts.append(article["summary"])
        
    # Add the main content sections
    if article.get("notes"):
        parts.append("\n## Notes")
        parts.append(article["notes"])
        
    # Format highlights
    if highlights:
        parts.append("\n## Highlights")
        for highlight in sorted(highlights, key=lambda x: x.get('position', 0)):
            content = highlight.get('content', '').strip()
            if content:
                parts.append(f"\n* {content}")
                if highlight.get('notes'):
                    parts.append(f"  \n  *Note: {highlight['notes']}*")
                    
    return "\n\n".join(parts)

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

from datetime import datetime, timezone
import logging
from time import sleep
from typing import Optional, Dict, List, Tuple
import requests

logger = logging.getLogger(__name__)

def main():
    """
    Main function to orchestrate the article synchronization process between Readwise Reader and Capacities.
    Handles all scenarios including emails, newsletters, articles, and YouTube content with proper error
    handling and rate limiting.
    """
    # Initialize our API clients with rate limiting and retry logic
    readwise_client = ReadwiseClient(READWISE_TOKEN)
    capacities_client = CapacitiesClient(CAPACITIES_TOKEN, CAPACITIES_SPACE_ID)
    
    try:
        # Initialize processing state
        processed_ids = get_processed_ids()
        reference_timestamp = get_reference_timestamp()
        logger.info(f"Starting sync process. Reference timestamp: {reference_timestamp}")
        
        # Step 1: Fetch all unprocessed articles with proper date filtering
        try:
            all_unprocessed_articles = readwise_client.get_articles_with_highlights(
                updated_after=reference_timestamp,
                processed_ids=processed_ids
            )
            logger.info(f"Found {len(all_unprocessed_articles)} total unprocessed articles")
        except Exception as e:
            logger.error(f"Failed to fetch articles from Readwise: {e}")
            return
            
        # Step 2: Apply our per-run limit and date verification
        articles_to_process = []
        for article in all_unprocessed_articles[:ARTICLES_PER_RUN]:
            if verify_article_date(article, reference_timestamp):
                articles_to_process.append(article)
            else:
                logger.debug(f"Skipping article '{article.get('title')}' - before reference date")
        
        logger.info(f"Processing batch of {len(articles_to_process)} articles")
        
        # Step 3: Process each article with comprehensive error handling
        processed_count = {'success': 0, 'error': 0, 'skipped': 0}
        
        for article in articles_to_process:
            article_id = article.get('id')
            title = article.get('title', 'Untitled')
            
            try:
                # Skip if already processed
                if article_id in processed_ids:
                    processed_count['skipped'] += 1
                    logger.debug(f"Skipping already processed article: {title}")
                    continue
                    
                # Handle URL processing and content type determination
                url, is_email = process_article_url(article)
                if not url:
                    processed_count['skipped'] += 1
                    logger.warning(f"Skipping article with invalid URL: {title}")
                    continue
                
                # Clean and prepare the title
                cleaned_title = title
                if "youtube.com" in url:
                    cleaned_title = clean_youtube_title(title)
                elif is_email and '🟡' in title:  # Handle emoji in email titles
                    cleaned_title = title.replace('🟡', '').strip()
                
                # Fetch and process highlights with rate limiting
                try:
                    highlights = readwise_client.get_highlights_for_article(article_id)
                    sleep(0.5)  # Basic rate limiting
                except Exception as e:
                    logger.error(f"Failed to fetch highlights for '{title}': {e}")
                    highlights = []
                
                # Format content based on type
                if is_email:
                    formatted_content = format_email_content(article, highlights)
                    description = "Email/Newsletter content saved from Readwise Reader"
                else:
                    notes_parts = []
                    
                    # Add reading progress if available
                    if article.get("reading_progress"):
                        progress = article["reading_progress"] * 100
                        notes_parts.append(f"**Reading Progress:** {progress:.1f}%")
                    
                    # Add original notes if available
                    if article.get("notes"):
                        notes_parts.append("\n## Notes")
                        notes_parts.append(article["notes"])
                    
                    # Add highlights if available
                    if highlights:
                        formatted_highlights = readwise_client.format_highlights_markdown(highlights)
                        if formatted_highlights:
                            notes_parts.append("\n" + formatted_highlights)
                    
                    formatted_content = "\n\n".join(notes_parts) if notes_parts else None
                    description = article.get("summary", "")
                
                # Prepare tags with proper categorization
                tags = list(article.get('tags', []))
                if is_email:
                    tags.append('email')
                elif "youtube.com" in url:
                    tags.append('youtube')
                if DEFAULT_TAGS:
                    tags.extend(DEFAULT_TAGS)
                
                # Create weblink with retry logic
                try:
                    created_weblink = capacities_client.create_weblink(
                    url=url,
                    title=cleaned_title,
                    description=description,
                    notes=formatted_content,
                    author=article.get("author", "Unknown"),
                    tags=tags,
                    content_type='email' if is_email else ('youtube' if 'youtube.com' in url else 'article')
                )
                    
                    processed_count['success'] += 1
                    logger.info(
                        f"Created weblink ({processed_count['success']}/{len(articles_to_process)}): "
                        f"{cleaned_title}"
                    )
                    
                    # Mark as processed only after successful creation
                    add_processed_id(article_id)
                    
                    # Rate limiting between requests
                    sleep(1)
                    
                except requests.exceptions.RequestException as e:
                    processed_count['error'] += 1
                    logger.error(f"API error creating weblink for '{cleaned_title}': {e}")
                    continue
                    
            except Exception as e:
                processed_count['error'] += 1
                logger.error(f"Unexpected error processing article '{title}': {e}")
                continue
        
        # Final summary logging
        logger.info(
            f"Processing completed. Results:\n"
            f"- Successfully created: {processed_count['success']} weblinks\n"
            f"- Errors: {processed_count['error']}\n"
            f"- Skipped: {processed_count['skipped']}\n"
        )
        
    except Exception as e:
        logger.error(f"Fatal error in main process: {e}")
        raise
        
    finally:
        # Any cleanup needed would go here
        pass

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Script failed with error: {e}")
        raise