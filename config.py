# config.py

import os
from datetime import datetime, timezone
from pathlib import Path

# API tokens from environment variables
READWISE_TOKEN = os.environ.get('READWISE_TOKEN')
CAPACITIES_TOKEN = os.environ.get('CAPACITIES_TOKEN')
CAPACITIES_SPACE_ID = os.environ.get('CAPACITIES_SPACE_ID')

# API endpoints
READWISE_LIST_URL = 'https://readwise.io/api/v3/list/'
CAPACITIES_BASE_URL = 'https://api.capacities.io'

# Processing configuration
ARTICLES_PER_RUN = 5
ARTICLES_UPDATED_AFTER = "2024-12-05"
DEFAULT_TAGS = ['pendente', 'readwise']

# File paths
PROCESSED_IDS_FILE = Path('processed_ids.txt')

# Ensure the processed IDs file exists
if not PROCESSED_IDS_FILE.exists():
    PROCESSED_IDS_FILE.touch()

def get_processed_ids():
    """Read the set of previously processed article IDs."""
    with open(PROCESSED_IDS_FILE, 'r') as f:
        return set(line.strip() for line in f if line.strip())

def add_processed_id(article_id):
    """Add a newly processed article ID to the tracking file."""
    with open(PROCESSED_IDS_FILE, 'a') as f:
        f.write(f'{article_id}\n')

def get_reference_timestamp() -> str:
    """
    Converts our reference date into the ISO 8601 format required by the Readwise API.
    Returns a properly formatted timestamp that includes time and timezone information.
    """
    try:
        reference_date = datetime.strptime(ARTICLES_UPDATED_AFTER, "%Y-%m-%d")
        reference_timestamp = reference_date.replace(
            hour=0, 
            minute=0, 
            second=0, 
            microsecond=0, 
            tzinfo=timezone.utc
        )
        return reference_timestamp.isoformat()
    except ValueError as e:
        raise ValueError(f"Invalid reference date format in config: {e}")