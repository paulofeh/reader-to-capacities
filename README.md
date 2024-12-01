# Reader to Capacities

Automatically import archived articles from Readwise Reader to Capacities, including highlights and notes.

## Setup

1. Fork this repository
2. Add your API tokens and Space ID as repository secrets:
   - `READWISE_TOKEN`
   - `CAPACITIES_TOKEN`
   - `CAPACITIES_SPACE_ID`
3. The workflow can be triggered manually from the Actions tab

## Configuration

- The script processes articles that were updated after the date specified in `src/config.py`
- Only archived articles are processed
- Articles are tracked in `processed_ids.txt` to avoid duplication

## Manual Execution

1. Go to the Actions tab in your repository
2. Select "Import Articles from Reader"
3. Click "Run workflow"
4. Optionally adjust the number of articles to process
5. Click "Run workflow"

## Development

To set up the development environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt