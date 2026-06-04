import os
import sys
import unittest
from pathlib import Path

# Add inference directory to path so imports work correctly
sys.path.append(str(Path(__file__).parent.parent / "inference"))

from storage import CorteonStorage
from nlp_pipeline import Tier1Processor
from inference_engine import InferenceEngine

class TestNLPAndNaming(unittest.TestCase):
    def setUp(self):
        # Use ~/.corteon/test_corteon.db for testing to ensure proper write permissions and SQLite WAL support
        self.db_path = Path.home() / ".corteon" / "test_corteon.db"
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except Exception:
                pass
        
        self.storage = CorteonStorage(db_path=self.db_path)
        self.storage.create_tables()
        
        self.nlp = Tier1Processor()
        
        # Override storage in a dummy InferenceEngine
        self.engine = InferenceEngine()
        self.engine.storage = self.storage
        self.engine.nlp = self.nlp

    def tearDown(self):
        self.storage.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_schema_has_extraction_failed(self):
        # Verify the captures table has the extraction_failed column
        conn = self.storage.conn
        cursor = conn.execute("PRAGMA table_info(captures)")
        columns = [row["name"] for row in cursor.fetchall()]
        self.assertIn("extraction_failed", columns)
        print("Schema verification: 'extraction_failed' column found in captures table.")

    def test_generate_auto_title_with_entities(self):
        # If nlp_result has entities, it should generate title from entity
        nlp_result = {
            "named_entities": [{"text": "Google LLC", "label": "ORG"}],
            "keywords_yake": ["search engine", "technology"],
            "noun_phrases": ["a search engine"],
            "embedding_vector": [0.1] * 384
        }
        title = self.nlp.generate_auto_title(nlp_result, markdown="Google is a search engine.", source_url="https://google.com")
        self.assertEqual(title, "Google Llc")
        print(f"Auto-title with entity: '{title}' (expected: 'Google Llc')")

    def test_generate_auto_title_with_keywords(self):
        # If nlp_result has no priority entities but has keywords, it should use the keyword
        nlp_result = {
            "named_entities": [],
            "keywords_yake": ["quantum computing", "physics"],
            "noun_phrases": ["quantum computing theory"],
            "embedding_vector": [0.1] * 384
        }
        title = self.nlp.generate_auto_title(nlp_result, markdown="Quantum computing is cool.", source_url="https://example.com")
        self.assertEqual(title, "Quantum Computing")
        print(f"Auto-title with keyword: '{title}' (expected: 'Quantum Computing')")

    def test_generate_auto_title_lazy_extraction(self):
        # If nlp_result is empty but valid markdown is provided, it should call process()
        # Note: Since spaCy/YAKE might not be installed, we mock self.nlp.process to return a mock result
        original_process = self.nlp.process
        self.nlp.process = lambda md, note="": {
            "named_entities": [{"text": "Apple Inc", "label": "ORG"}],
            "keywords_yake": ["iphone"],
            "noun_phrases": ["smartphones"],
            "embedding_vector": [0.1] * 384
        }
        try:
            title = self.nlp.generate_auto_title(None, markdown="Apple makes iPhones.", source_url="https://apple.com")
            self.assertEqual(title, "Apple Inc")
            print(f"Auto-title lazy extraction: '{title}' (expected: 'Apple Inc')")
        finally:
            self.nlp.process = original_process

    def test_empty_markdown_capture_sets_extraction_failed(self):
        # Test processing capture with empty markdown content
        import asyncio
        capture_payload = {
            "capture_id": "test_empty_md",
            "title": "",
            "content_markdown": "",  # Completely empty
            "user_note": "A note about nothing",
            "source_url": "https://example.com/empty"
        }
        
        # We can run the async method using asyncio.run or loop
        loop = asyncio.get_event_loop()
        class DummyWS:
            async def send(self, data):
                pass
        
        # Process the empty capture
        loop.run_until_complete(self.engine.process_capture(capture_payload, DummyWS()))
        
        # Query database and verify
        conn = self.storage.conn
        row = conn.execute("SELECT * FROM captures WHERE capture_id = 'test_empty_md'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["extraction_failed"], 1)
        self.assertEqual(row["prediction_error_score"], 0.0)
        self.assertEqual(row["semantic_novelty"], 0.0)
        print("Empty markdown test passed: extraction_failed=1, novelty=0.0 in database.")

    def test_valid_markdown_capture_clears_extraction_failed(self):
        # Test processing capture with valid markdown content
        import asyncio
        capture_payload = {
            "capture_id": "test_valid_md",
            "title": "My Title",
            "content_markdown": "This is valid markdown content detailing a new neural network architecture.",
            "user_note": "Interesting tech",
            "source_url": "https://example.com/neural"
        }
        
        # Mock nlp.process and prediction_error_score to avoid heavy models load if not available
        original_process = self.nlp.process
        self.nlp.process = lambda md, note="": {
            "named_entities": [],
            "keywords_yake": ["neural network"],
            "noun_phrases": [],
            "embedding_vector": [0.2] * 384
        }
        
        loop = asyncio.get_event_loop()
        class DummyWS:
            async def send(self, data):
                pass
                
        try:
            loop.run_until_complete(self.engine.process_capture(capture_payload, DummyWS()))
        finally:
            self.nlp.process = original_process
            
        conn = self.storage.conn
        row = conn.execute("SELECT * FROM captures WHERE capture_id = 'test_valid_md'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["extraction_failed"], 0)
        print("Valid markdown test passed: extraction_failed=0 in database.")

if __name__ == "__main__":
    unittest.main()
