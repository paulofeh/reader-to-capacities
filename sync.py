import requests
import json
from datetime import datetime, timezone
import os
from typing import Dict, List, Optional

class ReaderToCapacitiesSync:
    def __init__(self, reader_token: str, capacities_token: str, space_id: str):
        self.reader_token = reader_token
        self.capacities_token = capacities_token
        self.space_id = space_id
        self.sync_history_file = "sync_history.json"
        self.history = self.load_sync_history()
    
    def load_sync_history(self) -> Dict:
        """Load sync history from file or create if doesn't exist"""
        try:
            with open(self.sync_history_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {'last_sync': None, 'synced_articles': {}}

    def save_sync_history(self):
        """Save sync history to file"""
        with open(self.sync_history_file, 'w') as f:
            json.dump(self.history, f)

    def fetch_reader_documents(self, updated_after: Optional[str] = None) -> List[Dict]:
        """Fetch documents from Readwise Reader"""
        documents = []
        next_page_cursor = None

        while True:
            params = {}
            if next_page_cursor:
                params['pageCursor'] = next_page_cursor
            if updated_after:
                params['updatedAfter'] = updated_after

            response = requests.get(
                "https://readwise.io/api/v3/list/",
                params=params,
                headers={"Authorization": f"Token {self.reader_token}"}
            )
            
            if response.status_code != 200:
                raise Exception(f"Failed to fetch Reader documents: {response.text}")

            data = response.json()
            documents.extend(data['results'])
            next_page_cursor = data.get('nextPageCursor')

            if not next_page_cursor:
                break

        return documents

    def create_capacities_note(self, document: Dict) -> bool:
        """Create a note in Capacities for a Reader document"""
        # Prepare the markdown content
        md_content = f"""
# {document['title']}

{document.get('summary', '')}

**Author:** {document.get('author', 'Unknown')}
**Source:** {document.get('site_name', 'Unknown')}
**Published:** {document.get('published_date', 'Unknown')}
**Word Count:** {document.get('word_count', 'Unknown')}

**Original URL:** {document['source_url']}
**Reader URL:** {document['url']}

---

{document.get('notes', '')}
        """

        payload = {
            "spaceId": self.space_id,
            "url": document['source_url'],
            "titleOverwrite": document['title'][:500],  # Ensure within limit
            "descriptionOverwrite": (document.get('summary', '') or '')[:1000],  # Ensure within limit
            "mdText": md_content[:200000],  # Ensure within limit
            "tags": ["reader-import"]  # Add default tag
        }

        response = requests.post(
            "https://api.capacities.io/save-weblink",
            headers={
                "Authorization": f"Bearer {self.capacities_token}",
                "Content-Type": "application/json"
            },
            json=payload
        )

        if response.status_code in [200, 201]:
            return True
        else:
            print(f"Failed to create note for {document['title']}: {response.text}")
            return False

    def sync(self):
        """Main sync function"""
        try:
            # Get last sync time
            last_sync = self.history['last_sync']
            
            # Fetch documents from Reader
            documents = self.fetch_reader_documents(last_sync)
            
            synced_count = 0
            for doc in documents:
                # Skip if already synced
                if doc['id'] in self.history['synced_articles']:
                    continue
                
                # Create note in Capacities
                if self.create_capacities_note(doc):
                    self.history['synced_articles'][doc['id']] = {
                        'synced_at': datetime.now(timezone.utc).isoformat(),
                        'title': doc['title']
                    }
                    synced_count += 1

            # Update last sync time
            self.history['last_sync'] = datetime.now(timezone.utc).isoformat()
            
            # Save sync history
            self.save_sync_history()
            
            return {
                'success': True,
                'synced_count': synced_count,
                'total_documents': len(documents)
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

def main():
    # Load environment variables or configuration
    reader_token = os.getenv('READER_TOKEN')
    capacities_token = os.getenv('CAPACITIES_TOKEN')
    space_id = os.getenv('CAPACITIES_SPACE_ID')

    if not all([reader_token, capacities_token, space_id]):
        raise ValueError("Missing required environment variables")

    # Initialize and run sync
    syncer = ReaderToCapacitiesSync(reader_token, capacities_token, space_id)
    result = syncer.sync()
    
    if result['success']:
        print(f"Sync completed successfully. Synced {result['synced_count']} out of {result['total_documents']} documents.")
    else:
        print(f"Sync failed: {result['error']}")

if __name__ == "__main__":
    main()