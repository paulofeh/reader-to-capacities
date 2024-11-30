# Reader to Capacities Sync

This repository contains a GitHub Actions workflow that automatically syncs your Readwise Reader articles to Capacities.

## Setup

1. Fork this repository

2. Set up the following secrets in your GitHub repository (Settings > Secrets and variables > Actions):
   - `READER_TOKEN`: Your Readwise Reader API token
   - `CAPACITIES_TOKEN`: Your Capacities API token
   - `CAPACITIES_SPACE_ID`: Your Capacities space ID

3. The sync will run automatically every 6 hours. You can also trigger it manually from the Actions tab.

## How It Works

- The script fetches articles from your Readwise Reader account
- For each new article, it creates a weblink in your specified Capacities space
- Sync history is maintained in `sync_history.json` to prevent duplicates
- The workflow runs every 6 hours by default (configurable in `.github/workflows/sync.yml`)

## Repository Structure

```
.
├── .github/
│   └── workflows/
│       └── sync.yml      # GitHub Actions workflow configuration
├── sync.py              # Main sync script
├── requirements.txt     # Python dependencies
└── README.md           # This file
```

## Configuration

You can adjust the sync frequency by modifying the cron schedule in `.github/workflows/sync.yml`. The default is every 6 hours:

```yaml
on:
  schedule:
    - cron: '0 */6 * * *'  # Runs every 6 hours
```

## Manual Trigger

You can manually trigger the sync from the Actions tab in your GitHub repository. Click on "Reader to Capacities Sync" and then "Run workflow".