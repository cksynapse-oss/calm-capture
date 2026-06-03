"""
storage.py — CorteonStorage: SQLite persistence layer for Calm Capture.

Tables
------
captures        — enriched capture records from the browser extension
topic_clusters  — running cluster centroids for topic modelling
resurface_events— user interaction audit log
embeddings      — 384-dim float32 sentence embeddings stored as BLOBs
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import struct
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

DB_DIR = Path.home() / ".corteon"
DB_PATH = DB_DIR / "corteon.db"

NUM_EMBEDDING_DIMS = 384


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _array_to_blob(arr: np.ndarray) -> bytes:
    """Pack a float32 numpy array into a compact binary BLOB."""
    arr = arr.astype(np.float32)
    return struct.pack(f"{len(arr)}f", *arr)


def _blob_to_array(blob: bytes) -> np.ndarray:
    """Unpack a BLOB produced by _array_to_blob back into float32 ndarray."""
    n = len(blob) // 4  # 4 bytes per float32
    return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Numerically stable cosine similarity between two 1-D vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# CorteonStorage
# ---------------------------------------------------------------------------

class CorteonStorage:
    """
    Thread-compatible SQLite persistence for Calm Capture.

    Usage
    -----
    storage = CorteonStorage()
    storage.create_tables()
    storage.save_capture({...})
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = Path(db_path) if db_path else DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._connect()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        """Open (or re-open) the SQLite connection with sensible defaults."""
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=10.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        logger.info("Connected to SQLite at %s", self._db_path)

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._connect()
        return self._conn  # type: ignore[return-value]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Schema creation
    # ------------------------------------------------------------------

    def create_tables(self) -> None:
        """Create all tables if they do not already exist."""
        ddl_statements = [
            # ---------------------------------------------------------- captures
            """
            CREATE TABLE IF NOT EXISTS captures (
                capture_id          TEXT PRIMARY KEY,
                timestamp           REAL NOT NULL,
                source_url          TEXT,
                title               TEXT,
                auto_title          TEXT,
                user_note           TEXT,
                domain              TEXT,
                author              TEXT,
                word_count          INTEGER,
                content_type        TEXT,
                epistemic_type      TEXT DEFAULT 'pratyaksa',
                markdown_path       TEXT,
                keywords_json       TEXT,
                entities_json       TEXT,
                noun_phrases_json   TEXT,
                concepts_json       TEXT,
                one_sentence_summary TEXT,
                prediction_error_score REAL DEFAULT 0.0,
                semantic_novelty    REAL DEFAULT 0.0,
                user_emphasis       REAL DEFAULT 0.0,
                source_reliability  REAL DEFAULT 0.5,
                topic_cluster_id    INTEGER,
                familiarity_level   INTEGER DEFAULT 0,
                tier1_processed_at  REAL,
                created_at          REAL NOT NULL
            )
            """,
            # ------------------------------------------------------- topic_clusters
            """
            CREATE TABLE IF NOT EXISTS topic_clusters (
                cluster_id          INTEGER PRIMARY KEY,
                label               TEXT,
                centroid_json       TEXT,
                capture_count       INTEGER DEFAULT 0,
                created_at          REAL NOT NULL
            )
            """,
            # ----------------------------------------------------- resurface_events
            """
            CREATE TABLE IF NOT EXISTS resurface_events (
                event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
                capture_id          TEXT,
                timestamp           REAL NOT NULL,
                action              TEXT,
                efe_score           REAL,
                context_similarity  REAL,
                inferred_topic      INTEGER,
                duration_visible_ms INTEGER,
                FOREIGN KEY (capture_id) REFERENCES captures(capture_id)
            )
            """,
            # --------------------------------------------------------- embeddings
            """
            CREATE TABLE IF NOT EXISTS embeddings (
                capture_id  TEXT PRIMARY KEY,
                embedding   BLOB NOT NULL,
                FOREIGN KEY (capture_id) REFERENCES captures(capture_id)
            )
            """,
            # --------------------------------------------------- useful indexes
            "CREATE INDEX IF NOT EXISTS idx_captures_cluster ON captures(topic_cluster_id);",
            "CREATE INDEX IF NOT EXISTS idx_captures_pe ON captures(prediction_error_score DESC);",
            "CREATE INDEX IF NOT EXISTS idx_resurface_ts ON resurface_events(timestamp DESC);",
            "CREATE INDEX IF NOT EXISTS idx_captures_ts ON captures(timestamp DESC);",
        ]
        with self.conn:
            for ddl in ddl_statements:
                self.conn.execute(ddl)
        self._migrate_schema()
        logger.info("Tables verified/created.")

    def _migrate_schema(self) -> None:
        """Safely add new columns to existing tables (idempotent)."""
        migrations = [
            ("captures", "auto_title", "TEXT"),
            ("captures", "epistemic_type", "TEXT DEFAULT 'pratyaksa'"),
        ]
        for table, column, col_type in migrations:
            try:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                logger.info("Migrated: added %s.%s", table, column)
            except sqlite3.OperationalError:
                pass  # column already exists

    # ------------------------------------------------------------------
    # Captures
    # ------------------------------------------------------------------

    def save_capture(self, capture_dict: Dict[str, Any]) -> None:
        """
        Upsert a capture record into the captures table.

        If an 'embedding' key (np.ndarray or list) is present in
        capture_dict it is stored separately in the embeddings table and
        removed from the main record before insertion.
        """
        data = dict(capture_dict)  # shallow copy to avoid mutating caller's dict
        now = time.time()
        data.setdefault("created_at", now)
        data.setdefault("timestamp", now)

        # Extract embedding before inserting into captures table
        embedding_vector: Optional[np.ndarray] = None
        if "embedding" in data:
            raw = data.pop("embedding")
            if raw is not None:
                if isinstance(raw, list):
                    embedding_vector = np.array(raw, dtype=np.float32)
                elif isinstance(raw, np.ndarray):
                    embedding_vector = raw.astype(np.float32)

        # Columns that exist in the captures table
        capture_columns = {
            "capture_id", "timestamp", "source_url", "title", "auto_title",
            "user_note", "domain", "author", "word_count", "content_type",
            "epistemic_type", "markdown_path",
            "keywords_json", "entities_json", "noun_phrases_json", "concepts_json",
            "one_sentence_summary", "prediction_error_score", "semantic_novelty",
            "user_emphasis", "source_reliability", "topic_cluster_id",
            "familiarity_level", "tier1_processed_at", "created_at",
        }

        row = {k: v for k, v in data.items() if k in capture_columns}

        cols = ", ".join(row.keys())
        placeholders = ", ".join(["?"] * len(row))
        update_clause = ", ".join(f"{c}=excluded.{c}" for c in row if c != "capture_id")
        sql = (
            f"INSERT INTO captures ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(capture_id) DO UPDATE SET {update_clause}"
        )

        with self.conn:
            self.conn.execute(sql, list(row.values()))
            if embedding_vector is not None and "capture_id" in row:
                blob = _array_to_blob(embedding_vector)
                self.conn.execute(
                    """
                    INSERT INTO embeddings (capture_id, embedding)
                    VALUES (?, ?)
                    ON CONFLICT(capture_id) DO UPDATE SET embedding=excluded.embedding
                    """,
                    (row["capture_id"], blob),
                )
        logger.debug("Saved capture %s", row.get("capture_id"))

    # ------------------------------------------------------------------
    # Embeddings / similarity
    # ------------------------------------------------------------------

    def get_all_embeddings(self) -> List[Dict[str, Any]]:
        """
        Return all stored embeddings as a list of dicts::

            [{"capture_id": str, "embedding": np.ndarray}, ...]
        """
        cursor = self.conn.execute("SELECT capture_id, embedding FROM embeddings")
        results = []
        for row in cursor.fetchall():
            try:
                arr = _blob_to_array(row["embedding"])
                results.append({"capture_id": row["capture_id"], "embedding": arr})
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping malformed embedding for %s: %s", row["capture_id"], exc)
        return results

    def find_similar_captures(
        self, query_embedding: np.ndarray, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Perform in-Python cosine similarity search over all stored embeddings.

        Returns a list of dicts with keys: capture_id, score, (capture columns).
        """
        all_embs = self.get_all_embeddings()
        if not all_embs:
            return []

        query = np.array(query_embedding, dtype=np.float32)
        scored: List[tuple[float, str]] = []
        for item in all_embs:
            sim = _cosine_similarity(query, item["embedding"])
            scored.append((sim, item["capture_id"]))

        scored.sort(reverse=True)
        top_ids = [cid for _, cid in scored[:limit]]
        top_scores = {cid: score for score, cid in scored[:limit]}

        if not top_ids:
            return []

        placeholders = ",".join(["?"] * len(top_ids))
        rows = self.conn.execute(
            f"SELECT * FROM captures WHERE capture_id IN ({placeholders})", top_ids
        ).fetchall()

        result = []
        for row in rows:
            d = dict(row)
            d["score"] = top_scores.get(d["capture_id"], 0.0)
            result.append(d)
        result.sort(key=lambda x: x["score"], reverse=True)
        return result

    # ------------------------------------------------------------------
    # Resurface candidates
    # ------------------------------------------------------------------

    def get_resurface_candidates(
        self, topic_id: Optional[int], limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Return top captures for resurfacing, ordered by prediction_error_score DESC.

        If topic_id is None, returns global top-PE captures.
        """
        if topic_id is not None:
            rows = self.conn.execute(
                """
                SELECT * FROM captures
                WHERE topic_cluster_id = ?
                ORDER BY prediction_error_score DESC
                LIMIT ?
                """,
                (topic_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM captures
                ORDER BY prediction_error_score DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Resurface events
    # ------------------------------------------------------------------

    def log_resurface_event(
        self,
        capture_id: str,
        action: str,
        efe_score: float,
        context_similarity: float,
        inferred_topic: Optional[int],
        duration_visible_ms: int = 0,
    ) -> None:
        """Append a resurface interaction record."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO resurface_events
                    (capture_id, timestamp, action, efe_score,
                     context_similarity, inferred_topic, duration_visible_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    time.time(),
                    action,
                    efe_score,
                    context_similarity,
                    inferred_topic,
                    duration_visible_ms,
                ),
            )
        logger.debug("Logged resurface event: %s / %s", capture_id, action)

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    def get_recent_capture_status(self) -> int:
        """
        Return capture activity level in the last 60 seconds as an int 0-3:
            0 — no captures
            1 — 1 capture (same topic likely)
            2 — 2+ captures (new topic activity)
            3 — capture with non-empty user_note (strong note signal)
        """
        since = time.time() - 60.0
        rows = self.conn.execute(
            "SELECT user_note FROM captures WHERE timestamp >= ? ORDER BY timestamp DESC",
            (since,),
        ).fetchall()
        if not rows:
            return 0
        if any(r["user_note"] and r["user_note"].strip() for r in rows):
            return 3
        if len(rows) >= 2:
            return 2
        return 1

    def get_last_feedback(self) -> int:
        """
        Map the most recent resurface event's action to an int 0-3:
            0 — no_overlay / no event
            1 — clicked
            2 — dismissed
            3 — ignored (shown but no interaction)
        """
        row = self.conn.execute(
            "SELECT action FROM resurface_events ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return 0
        action_map = {
            "clicked": 1,
            "click": 1,
            "dismissed": 2,
            "dismiss": 2,
            "ignored": 3,
            "ignore": 3,
        }
        return action_map.get(str(row["action"]).lower(), 0)

    # ------------------------------------------------------------------
    # Topic clusters
    # ------------------------------------------------------------------

    def upsert_topic_cluster(
        self,
        cluster_id: int,
        label: str,
        centroid: np.ndarray,
        capture_count: int,
    ) -> None:
        """Upsert a topic cluster record."""
        centroid_json = json.dumps(centroid.tolist())
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO topic_clusters (cluster_id, label, centroid_json, capture_count, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    label=excluded.label,
                    centroid_json=excluded.centroid_json,
                    capture_count=excluded.capture_count
                """,
                (cluster_id, label, centroid_json, capture_count, time.time()),
            )

    def get_topic_centroids(self) -> List[Dict[str, Any]]:
        """Return all topic clusters with centroid as np.ndarray."""
        rows = self.conn.execute(
            "SELECT cluster_id, label, centroid_json, capture_count FROM topic_clusters"
        ).fetchall()
        result = []
        for row in rows:
            try:
                centroid = np.array(json.loads(row["centroid_json"]), dtype=np.float32)
                result.append(
                    {
                        "cluster_id": row["cluster_id"],
                        "label": row["label"],
                        "centroid": centroid,
                        "capture_count": row["capture_count"],
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Bad centroid for cluster %s: %s", row["cluster_id"], exc)
        return result

    def update_capture_cluster(self, capture_id: str, cluster_id: int) -> None:
        """Assign a topic_cluster_id to an existing capture."""
        with self.conn:
            self.conn.execute(
                "UPDATE captures SET topic_cluster_id=? WHERE capture_id=?",
                (cluster_id, capture_id),
            )
