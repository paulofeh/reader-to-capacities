# Readwise Reader to Capacities Sync

This project automates the synchronization of archived articles from Readwise Reader to Capacities, helping maintain a well-organized Personal Knowledge Management (PKM) system. The script fetches articles you've archived in Readwise Reader, including their highlights and notes, and creates corresponding weblinks in your Capacities workspace.

## Key Features

The synchronization process includes:
- Fetches only archived articles from Readwise Reader, ensuring intentional content curation
- Transfers article metadata including title, description, and author
- Preserves all highlights and notes made in Readwise Reader
- Maintains a history of processed articles to prevent duplicates
- Processes articles in configurable batches to manage API usage
- Runs manually through GitHub Actions with secure credential handling

## Prerequisites

Before setting up this project, you'll need:
- A Readwise Reader account with API access
- A Capacities account with API access
- A GitHub account for hosting the workflow
- Python 3.10 or higher for local development

## Setup Instructions

### Local Development Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/reader-to-capacities.git
cd reader-to-capacities
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
# On Windows
venv\Scripts\activate
# On macOS/Linux
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root with your API credentials:
```plaintext
READWISE_TOKEN=your_readwise_token
CAPACITIES_TOKEN=your_capacities_token
CAPACITIES_SPACE_ID=your_space_id
```

### GitHub Setup

1. Create a new repository on GitHub

2. Add the following secrets in your repository settings (Settings > Secrets and variables > Actions):
- `READWISE_TOKEN`: Your Readwise API token
- `CAPACITIES_TOKEN`: Your Capacities API token
- `CAPACITIES_SPACE_ID`: Your Capacities space ID

3. Push your code to GitHub:
```bash
git remote add origin https://github.com/yourusername/reader-to-capacities.git
git branch -M main
git push -u origin main
```

## Configuration

The script's behavior can be customized through the `config.py` file:

- `ARTICLES_PER_RUN`: Number of articles to process in each execution (default: 5)
- `ARTICLES_UPDATED_AFTER`: Starting date for fetching updated articles (format: "YYYY-MM-DD")

## Usage

### Local Execution

To run the script locally:
```bash
python main.py
```

### GitHub Actions

To run the sync through GitHub Actions:
1. Go to your repository on GitHub
2. Click the "Actions" tab
3. Select "Sync Readwise Articles to Capacities"
4. Click "Run workflow"
5. Select the branch (usually 'main')
6. Click "Run workflow"

## How It Works

1. The script fetches archived articles from Readwise Reader that were updated after the specified date
2. For each article:
   - Retrieves associated highlights and notes
   - Creates a weblink in Capacities with:
     - Original article title and URL
     - Author information
     - Description/summary
     - Highlights formatted in markdown
     - Any additional notes
3. Maintains a list of processed articles to prevent duplicates
4. Updates the processing history in the repository

## Project Structure

```plaintext
reader-to-capacities/
├── .github/
│   └── workflows/
│       └── sync_articles.yml    # GitHub Actions workflow
├── .gitignore                   # Git ignore configuration
├── config.py                    # Configuration settings
├── main.py                      # Main script
├── capacities_client.py         # Capacities API client
├── requirements.txt             # Python dependencies
├── processed_ids.txt            # Processing history
└── README.md                    # Project documentation
```

## Error Handling

The script includes robust error handling for common scenarios:
- API rate limiting
- Network connectivity issues
- Invalid article formats
- Missing highlights or metadata

## Contributing

Feel free to submit issues and enhancement requests. All contributions are welcome!

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

This project was built using:
- [Readwise Reader API](https://readwise.io/api_deets)
- [Capacities API](https://api.capacities.io)