"""
nlp_pipeline.py — Tier-1 NLP processing for Calm Capture.

Responsibilities
----------------
* Keyword extraction (YAKE)
* Named-entity recognition (spaCy)
* Noun-phrase chunking (spaCy)
* Sentence embedding (sentence-transformers all-MiniLM-L6-v2)
* Prediction-error score (semantic novelty vs. corpus)
* Source-reliability heuristic
* User-emphasis heuristic
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_DIM = 384
YAKE_TOP_N = 10

# Reliability tiers keyed by exact domain substring (longest match wins)
_HIGH_RELIABILITY_DOMAINS = {
    "arxiv.org", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",
    "nature.com", "science.org", "cell.com", "thelancet.com",
    "jamanetwork.com", "bmj.com", "nejm.org", "pnas.org",
    "ieeexplore.ieee.org", "dl.acm.org", "springer.com",
    "wiley.com", "oup.com", "tandfonline.com",
    "scholar.google.com", "semanticscholar.org",
}
_MEDIUM_RELIABILITY_DOMAINS = {
    "substack.com", "medium.com", "wordpress.com", "ghost.io",
    "hashnode.dev", "dev.to", "hackernoon.com", "towardsdatascience.com",
    "towards-ai.net", "analyticsvidhya.com",
}


# ---------------------------------------------------------------------------
# Tier1Processor
# ---------------------------------------------------------------------------

class Tier1Processor:
    """
    Lazy-loading NLP processor.

    Models are not loaded until the first call to :meth:`process`
    or :meth:`prediction_error_score`, keeping startup time fast.
    """

    def __init__(self) -> None:
        self.nlp = None          # spaCy Language pipeline
        self.embedder = None     # SentenceTransformer
        self.kw_extractor = None # yake.KeywordExtractor
        self._models_loaded = False

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_models(self) -> None:
        """Load all heavy models exactly once."""
        if self._models_loaded:
            return

        logger.info("Loading NLP models (first call) …")

        # ---- spaCy ----
        try:
            import spacy  # noqa: PLC0415
            try:
                self.nlp = spacy.load("en_core_web_sm")
                logger.info("spaCy en_core_web_sm loaded.")
            except OSError:
                logger.warning(
                    "spaCy model en_core_web_sm not found. "
                    "Run: python -m spacy download en_core_web_sm"
                )
                # Minimal fallback — tokenization only
                self.nlp = spacy.blank("en")
        except ImportError:
            logger.error("spaCy is not installed. NER and noun-phrase extraction unavailable.")
            self.nlp = None

        # ---- SentenceTransformer ----
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
            self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("SentenceTransformer all-MiniLM-L6-v2 loaded.")
        except ImportError:
            logger.error("sentence-transformers not installed. Embeddings unavailable.")
            self.embedder = None
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to load SentenceTransformer: %s", exc)
            self.embedder = None

        # ---- YAKE ----
        try:
            import yake  # noqa: PLC0415
            self.kw_extractor = yake.KeywordExtractor(
                lan="en",
                n=3,           # up to 3-gram keywords
                dedupLim=0.7,
                top=YAKE_TOP_N,
                features=None,
            )
            logger.info("YAKE keyword extractor loaded.")
        except ImportError:
            logger.error("yake not installed. Keyword extraction unavailable.")
            self.kw_extractor = None
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to init YAKE: %s", exc)
            self.kw_extractor = None

        self._models_loaded = True
        logger.info("All NLP models initialised.")

    # ------------------------------------------------------------------
    # Text utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_markdown(markdown: str) -> str:
        """Strip Markdown formatting to produce plain text for NLP."""
        # Remove fenced code blocks
        text = re.sub(r"```[\s\S]*?```", " ", markdown)
        text = re.sub(r"`[^`]+`", " ", text)
        # Remove images and links — keep link text
        text = re.sub(r"!\[.*?\]\(.*?\)", " ", text)
        text = re.sub(r"\[([^\]]+)\]\([^\)]*\)", r"\1", text)
        # Remove ATX headings markers
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Remove bold/italic
        text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)
        # Remove block-quotes
        text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
        # Remove horizontal rules
        text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _normalize_vector(vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec)
        if norm == 0.0:
            return vec
        return vec / norm

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    def process(self, markdown: str, user_note: str = "") -> Dict[str, Any]:
        """
        Run Tier-1 NLP on a captured document.

        Parameters
        ----------
        markdown : str
            The full Markdown content of the captured page.
        user_note : str, optional
            The user's free-text annotation at capture time.

        Returns
        -------
        dict with keys:
            keywords_yake     : list[str]              — top YAKE_TOP_N keywords
            named_entities    : list[{text, label}]    — spaCy NER results
            noun_phrases      : list[str]              — spaCy noun chunks
            embedding_vector  : list[float]            — 384-dim normalised embedding
            note_embedding    : list[float]            — 384-dim normalised note embedding
        """
        self._load_models()
        plain_text = self._clean_markdown(markdown)

        result: Dict[str, Any] = {
            "keywords_yake": [],
            "named_entities": [],
            "noun_phrases": [],
            "embedding_vector": [0.0] * EMBEDDING_DIM,
            "note_embedding": [0.0] * EMBEDDING_DIM,
        }

        # ---- Keywords ----
        if self.kw_extractor and plain_text:
            try:
                kw_pairs = self.kw_extractor.extract_keywords(plain_text)
                result["keywords_yake"] = [kw for kw, _score in kw_pairs]
            except Exception as exc:  # noqa: BLE001
                logger.warning("YAKE extraction failed: %s", exc)

        # ---- spaCy (NER + noun-phrases) ----
        if self.nlp and plain_text:
            try:
                # Limit to first 100k chars to avoid spaCy memory issues
                doc = self.nlp(plain_text[:100_000])
                result["named_entities"] = [
                    {"text": ent.text, "label": ent.label_}
                    for ent in doc.ents
                ]
                result["noun_phrases"] = [
                    chunk.text for chunk in doc.noun_chunks
                ][:200]  # cap list length
            except Exception as exc:  # noqa: BLE001
                logger.warning("spaCy processing failed: %s", exc)

        # ---- Embeddings ----
        if self.embedder:
            try:
                # Document embedding — use first 512 tokens worth of text
                truncated = plain_text[:4096] if plain_text else "empty document"
                raw_emb = self.embedder.encode(truncated, convert_to_numpy=True)
                emb = self._normalize_vector(np.array(raw_emb, dtype=np.float32))
                result["embedding_vector"] = emb.tolist()

                # Note embedding
                note_text = user_note.strip() if user_note else ""
                if note_text:
                    raw_note = self.embedder.encode(note_text, convert_to_numpy=True)
                    note_emb = self._normalize_vector(np.array(raw_note, dtype=np.float32))
                else:
                    note_emb = emb  # fall back to document embedding
                result["note_embedding"] = note_emb.tolist()

            except Exception as exc:  # noqa: BLE001
                logger.error("Embedding failed: %s", exc)

        return result

    # ------------------------------------------------------------------
    # Prediction-error score
    # ------------------------------------------------------------------

    def prediction_error_score(
        self,
        embedding: List[float],
        all_embeddings: List[Dict[str, Any]],
    ) -> float:
        """
        Compute semantic novelty of *embedding* vs. the corpus.

        Score = 1 − max_cosine_similarity(embedding, corpus)

        Returns a float in [0, 1].  A score of 1.0 means the embedding is
        completely novel; 0.0 means a perfect duplicate exists.
        """
        if not all_embeddings:
            return 1.0  # first item is maximally novel

        query = np.array(embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query)
        if query_norm == 0.0:
            return 0.5

        max_sim = 0.0
        for item in all_embeddings:
            vec = item.get("embedding")
            if vec is None:
                continue
            if isinstance(vec, list):
                vec = np.array(vec, dtype=np.float32)
            else:
                vec = vec.astype(np.float32)

            vec_norm = np.linalg.norm(vec)
            if vec_norm == 0.0:
                continue
            sim = float(np.dot(query, vec) / (query_norm * vec_norm))
            if sim > max_sim:
                max_sim = sim

        return float(np.clip(1.0 - max_sim, 0.0, 1.0))

    # ------------------------------------------------------------------
    # Heuristics
    # ------------------------------------------------------------------

    @staticmethod
    def source_reliability(domain: str) -> float:
        """
        Map a domain string to a reliability score in [0, 1].

        Tier mapping
        ------------
        High  (0.95) : peer-reviewed journals, preprint servers, gov databases
        Medium (0.70) : personal blogs, newsletters
        Unknown (0.50): anything else
        """
        if not domain:
            return 0.5
        d = domain.lower().lstrip("www.")
        for known in _HIGH_RELIABILITY_DOMAINS:
            if d == known or d.endswith("." + known):
                return 0.95
        for known in _MEDIUM_RELIABILITY_DOMAINS:
            if d == known or d.endswith("." + known):
                return 0.70
        return 0.50

    @staticmethod
    def user_emphasis(note: str) -> float:
        """
        Estimate how much the user emphasised a capture from their note.

        Signals considered:
        * Exclamation marks (weighted at 0.15 each, cap 3)
        * ALL-CAPS word ratio
        * Note length (longer notes signal higher intent)

        Returns a float in [0, 1].
        """
        if not note or not note.strip():
            return 0.0

        text = note.strip()

        # --- exclamation mark signal ---
        excl_count = text.count("!")
        excl_score = min(excl_count * 0.15, 0.45)

        # --- ALL-CAPS signal ---
        words = re.findall(r"\b[A-Za-z]{2,}\b", text)
        caps_ratio = (
            sum(1 for w in words if w.isupper()) / len(words)
            if words else 0.0
        )
        caps_score = min(caps_ratio * 0.40, 0.40)

        # --- length signal (log-scaled up to ~200 chars = 0.15 max) ---
        length_score = min(np.log1p(len(text)) / np.log1p(200) * 0.15, 0.15)

        total = excl_score + caps_score + length_score
        return float(np.clip(total, 0.0, 1.0))

    # ------------------------------------------------------------------
    # Convenience: embed a single piece of text
    # ------------------------------------------------------------------

    def embed_text(self, text: str) -> Optional[np.ndarray]:
        """Return a normalised 384-dim float32 embedding, or None on failure."""
        self._load_models()
        if self.embedder is None:
            return None
        try:
            raw = self.embedder.encode(text[:4096], convert_to_numpy=True)
            return self._normalize_vector(np.array(raw, dtype=np.float32))
        except Exception as exc:  # noqa: BLE001
            logger.error("embed_text failed: %s", exc)
            return None
