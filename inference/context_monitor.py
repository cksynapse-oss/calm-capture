"""
context_monitor.py — ContextMonitor: gathers real-time environmental signals
for the Calm Capture active inference loop.

Design principles
-----------------
* Zero Accessibility permissions required — we query only the frontmost
  app NAME via osascript (a public AppleScript call that needs no special
  entitlements on macOS 13+).
* The browser extension owns URL/title; we receive them via WebSocket.
* Temporal signal is derived from the last resurface event timestamp
  stored in SQLite.
* Embeddings are lazy-loaded: the sentence-transformer model is not
  initialised until the first call that needs it.
"""

from __future__ import annotations

import logging
import subprocess
import time
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

NUM_TOPICS = 8  # must match active_inference_agent.NUM_TOPICS


# ---------------------------------------------------------------------------
# ContextMonitor
# ---------------------------------------------------------------------------

class ContextMonitor:
    """
    Collects and encodes environmental context into discrete observation
    indices that can be fed directly to :class:`CorteonAgent`.

    Observation tuple layout (mirrors the agent's modality definitions):

        (context_obs, capture_obs, temporal_obs, feedback_obs)

    with an additional ``context_embedding`` key for similarity searches.
    """

    def __init__(self) -> None:
        self.embedder = None            # SentenceTransformer — lazy
        self.storage = None             # CorteonStorage instance — injected
        self._models_loaded: bool = False

        # Current tab context (updated by the extension via WebSocket)
        self.last_tab_context: Dict[str, str] = {
            "url": "",
            "title": "",
        }

        # Cache last computed embedding to avoid re-embedding the same URL
        self._last_context_text: str = ""
        self._last_context_embedding: Optional[np.ndarray] = None

    # ------------------------------------------------------------------
    # Dependency injection
    # ------------------------------------------------------------------

    def set_storage(self, storage_instance: Any) -> None:
        """Inject the shared CorteonStorage instance."""
        self.storage = storage_instance
        logger.debug("ContextMonitor: storage attached.")

    # ------------------------------------------------------------------
    # Tab context (from browser extension)
    # ------------------------------------------------------------------

    def set_tab_context(self, url: str, title: str) -> None:
        """
        Update the monitor with the active browser tab's URL and title.

        Called by the WebSocket handler whenever the extension reports
        a tab activation or navigation event.
        """
        self.last_tab_context = {"url": url.strip(), "title": title.strip()}
        logger.debug("Tab context updated: %s | %s", url[:80], title[:60])

    # ------------------------------------------------------------------
    # Main observation builder
    # ------------------------------------------------------------------

    def get_current_observation(self) -> Dict[str, Any]:
        """
        Compute the current 4-tuple of discrete observation indices.

        Returns
        -------
        dict with keys:
            context_obs       : int  0-8   (0=unrecognised, 1-8=topic cluster)
            capture_obs       : int  0-3   (from storage.get_recent_capture_status)
            temporal_obs      : int  0-2   (recency of last resurface)
            feedback_obs      : int  0-3   (latest UI feedback)
            context_embedding : np.ndarray | None  (384-dim float32)
        """
        context_embedding = self._get_context_embedding()

        # Observation 0: Active Context
        if context_embedding is not None and self.storage is not None:
            topic_id = self._nearest_topic(context_embedding, self.storage)
            context_obs = min(topic_id + 1, NUM_TOPICS)  # 1-indexed; 0=unrecognised
        else:
            context_obs = 0

        # Observation 1: Capture Activity
        if self.storage is not None:
            try:
                capture_obs = int(self.storage.get_recent_capture_status())
            except Exception as exc:  # noqa: BLE001
                logger.warning("get_recent_capture_status failed: %s", exc)
                capture_obs = 0
        else:
            capture_obs = 0

        # Observation 2: Temporal Signal
        if self.storage is not None:
            try:
                temporal_obs = self._get_temporal_bucket(self.storage)
            except Exception as exc:  # noqa: BLE001
                logger.warning("_get_temporal_bucket failed: %s", exc)
                temporal_obs = 1
        else:
            temporal_obs = 1

        # Observation 3: UI Feedback
        if self.storage is not None:
            try:
                feedback_obs = int(self.storage.get_last_feedback())
            except Exception as exc:  # noqa: BLE001
                logger.warning("get_last_feedback failed: %s", exc)
                feedback_obs = 0
        else:
            feedback_obs = 0

        return {
            "context_obs": context_obs,
            "capture_obs": capture_obs,
            "temporal_obs": temporal_obs,
            "feedback_obs": feedback_obs,
            "context_embedding": context_embedding,
        }

    # ------------------------------------------------------------------
    # App name (zero Accessibility permission)
    # ------------------------------------------------------------------

    def _get_app_name(self) -> str:
        """
        Return the name of the current frontmost macOS application.

        Uses:
            osascript -e 'tell application "System Events"
                          to get name of first process whose frontmost is true'

        This call requires NO special Accessibility permissions on macOS —
        it only reads the process name, not window contents.

        Returns empty string on failure.
        """
        try:
            script = (
                'tell application "System Events" '
                'to get name of first process whose frontmost is true'
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except FileNotFoundError:
            logger.debug("osascript not found (non-macOS environment).")
        except subprocess.TimeoutExpired:
            logger.debug("osascript timed out.")
        except Exception as exc:  # noqa: BLE001
            logger.debug("_get_app_name failed: %s", exc)
        return ""

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def _load_embedder(self) -> None:
        """Lazy-load the SentenceTransformer model."""
        if self._models_loaded:
            return
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
            self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
            self._models_loaded = True
            logger.info("ContextMonitor: SentenceTransformer loaded.")
        except ImportError:
            logger.error("sentence-transformers not installed. Context embeddings unavailable.")
            self._models_loaded = True  # don't retry endlessly
        except Exception as exc:  # noqa: BLE001
            logger.error("ContextMonitor: embedder load failed: %s", exc)
            self._models_loaded = True

    def _embed_text(self, text: str) -> Optional[np.ndarray]:
        """
        Encode *text* into a normalised 384-dim float32 embedding.

        Returns None if the embedder is unavailable.
        """
        self._load_embedder()
        if self.embedder is None:
            return None
        try:
            raw = self.embedder.encode(text[:2048], convert_to_numpy=True)
            vec = np.array(raw, dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec /= norm
            return vec
        except Exception as exc:  # noqa: BLE001
            logger.warning("_embed_text failed: %s", exc)
            return None

    def _get_context_embedding(self) -> Optional[np.ndarray]:
        """
        Build a context string from the current tab + app name, then embed it.

        Caches the result so repeated calls within the same context
        do not re-run the model.
        """
        app_name = self._get_app_name()
        url = self.last_tab_context.get("url", "")
        title = self.last_tab_context.get("title", "")

        context_text = " ".join(filter(None, [app_name, title, url])).strip()
        if not context_text:
            return self._last_context_embedding

        if context_text == self._last_context_text and self._last_context_embedding is not None:
            return self._last_context_embedding

        embedding = self._embed_text(context_text)
        self._last_context_text = context_text
        self._last_context_embedding = embedding
        return embedding

    # ------------------------------------------------------------------
    # Temporal bucket
    # ------------------------------------------------------------------

    @staticmethod
    def _get_temporal_bucket(storage: Any) -> int:
        """
        Return a temporal observation bucket based on the last resurface event.

            0 — recent   : last event < 5 minutes ago
            1 — moderate : 5–30 minutes ago
            2 — stale    : > 30 minutes ago (or no events yet)
        """
        try:
            row = storage.conn.execute(
                "SELECT timestamp FROM resurface_events ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        except Exception as exc:  # noqa: BLE001
            logger.warning("_get_temporal_bucket DB query failed: %s", exc)
            return 2

        if row is None:
            return 2  # no resurface events yet → stale

        elapsed = time.time() - float(row["timestamp"])
        if elapsed < 5 * 60:
            return 0   # recent
        if elapsed < 30 * 60:
            return 1   # moderate
        return 2       # stale

    # ------------------------------------------------------------------
    # Nearest topic
    # ------------------------------------------------------------------

    def _nearest_topic(self, embedding: np.ndarray, storage: Any) -> int:
        """
        Find the nearest topic cluster by cosine similarity.

        Returns the cluster_id of the nearest centroid, or NUM_TOPICS (=8)
        if no clusters have been created yet (causes context_obs=0 upstream).
        """
        try:
            clusters = storage.get_topic_centroids()
        except Exception as exc:  # noqa: BLE001
            logger.warning("_nearest_topic: get_topic_centroids failed: %s", exc)
            return NUM_TOPICS

        if not clusters:
            return NUM_TOPICS  # no clusters yet

        best_id = NUM_TOPICS
        best_sim = -1.0
        q_norm = np.linalg.norm(embedding)
        if q_norm == 0.0:
            return NUM_TOPICS

        for cluster in clusters:
            centroid = cluster["centroid"]
            c_norm = np.linalg.norm(centroid)
            if c_norm == 0.0:
                continue
            sim = float(np.dot(embedding, centroid) / (q_norm * c_norm))
            if sim > best_sim:
                best_sim = sim
                best_id = int(cluster["cluster_id"])

        # If best similarity is extremely low, treat as unrecognised
        if best_sim < 0.20:
            return NUM_TOPICS

        return best_id
