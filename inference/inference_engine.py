"""
inference_engine.py — InferenceEngine: orchestrates all Calm Capture components.

Architecture
------------
                  ┌─────────────────────────────────────────┐
                  │          Chrome Extension                │
                  │  (captures, tab-context, feedback)       │
                  └───────────────┬─────────────────────────┘
                                  │ WebSocket ws://localhost:9741/inference
                  ┌───────────────▼─────────────────────────┐
                  │           InferenceEngine                │
                  │  ┌──────────────────────────────────┐   │
                  │  │  Tier1Processor (nlp_pipeline)   │   │
                  │  │  CorteonAgent  (active_inference) │   │
                  │  │  ContextMonitor                  │   │
                  │  │  CorteonStorage (SQLite)         │   │
                  │  └──────────────────────────────────┘   │
                  └─────────────────────────────────────────┘

Message protocol (JSON over WebSocket)
---------------------------------------
Incoming (from extension):
    { "type": "capture",     "payload": { capture fields ... } }
    { "type": "tab_context", "payload": { "url": "...", "title": "..." } }
    { "type": "feedback",    "payload": { "capture_id": "...", "action": "clicked"|"dismissed"|"ignored", "duration_ms": 0 } }
    { "type": "ping" }

Outgoing (to extension):
    { "type": "resurface",   "payload": { "captures": [...], "display_intensity": 0|1|2, "inferred_topic": 0-7, "inferred_need": "..." } }
    { "type": "pong" }
    { "type": "ack",         "capture_id": "..." }
    { "type": "error",       "message": "..." }
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Logging setup (before any local imports so handlers are installed early)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("inference_engine")

# ---------------------------------------------------------------------------
# Local imports (graceful degradation if a module is missing)
# ---------------------------------------------------------------------------
try:
    from storage import CorteonStorage
except ImportError as _e:
    logger.critical("Cannot import storage.py: %s", _e)
    sys.exit(1)

try:
    from nlp_pipeline import Tier1Processor
except ImportError as _e:
    logger.critical("Cannot import nlp_pipeline.py: %s", _e)
    sys.exit(1)

try:
    from active_inference_agent import CorteonAgent
except ImportError as _e:
    logger.critical("Cannot import active_inference_agent.py: %s", _e)
    sys.exit(1)

try:
    from context_monitor import ContextMonitor
except ImportError as _e:
    logger.critical("Cannot import context_monitor.py: %s", _e)
    sys.exit(1)

try:
    from clustering import run_kmeans_clustering
except ImportError as _e:
    logger.critical("Cannot import clustering.py: %s", _e)
    sys.exit(1)

try:
    from obsidian_exporter import sync_all_captures_to_obsidian, export_to_obsidian
except ImportError as _e:
    logger.critical("Cannot import obsidian_exporter.py: %s", _e)
    sys.exit(1)

try:
    import websockets
    from websockets.server import WebSocketServerProtocol
except ImportError:
    logger.critical(
        "websockets package not found. Install with: pip install websockets"
    )
    sys.exit(1)

import numpy as np  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DAEMON_URI = "ws://localhost:9741"   # Rust daemon WebSocket server
REGISTRATION_FRAME = '{"path":"/inference"}'  # First frame to send after connect
CONTEXT_LOOP_INTERVAL = 5.0          # seconds between context polls
MAX_RESURFACE_CANDIDATES = 5
RECONNECT_DELAY = 3.0                # seconds before retrying after disconnect
RESURFACE_COOLDOWN = 60.0            # seconds to wait before allowing another resurface popup


# ---------------------------------------------------------------------------
# InferenceEngine
# ---------------------------------------------------------------------------

class InferenceEngine:
    """
    Top-level orchestrator — WebSocket CLIENT connecting to the Rust daemon.

    Lifecycle
    ---------
    1. __init__  — create all subsystems
    2. run()     — connect to daemon at ws://localhost:9741, send registration,
                   start context_loop, listen for inbound messages forever.
                   Reconnects on disconnect.
    """

    def __init__(self) -> None:
        logger.info("Initialising InferenceEngine…")

        self.storage = CorteonStorage()
        self.storage.create_tables()

        self.nlp = Tier1Processor()
        self.agent = CorteonAgent()

        self.context_monitor = ContextMonitor()
        self.context_monitor.set_storage(self.storage)

        # Shared last-inference result (updated by context_loop)
        self._last_inference: Dict[str, Any] = {
            "resurface_action": 0,
            "display_intensity": 0,
            "inferred_topic": 0,
            "inferred_need": "Idle",
        }

        self._last_resurface_time = 0.0

        logger.info("InferenceEngine ready.")

    # ------------------------------------------------------------------
    # Entry-point — client connection loop with reconnect
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Connect to the Rust daemon and process messages forever, reconnecting on disconnect."""
        # Initial run of clustering and Obsidian sync
        try:
            loop = asyncio.get_event_loop()
            logger.info("Running initial topic clustering...")
            await loop.run_in_executor(None, run_kmeans_clustering, self.storage)
            logger.info("Running initial Obsidian vault sync...")
            await loop.run_in_executor(None, sync_all_captures_to_obsidian, self.storage)
        except Exception as exc:
            logger.warning("Failed during startup clustering/Obsidian sync: %s", exc)

        logger.info("Connecting to Rust daemon at %s", DAEMON_URI)
        while True:
            try:
                async with websockets.connect(
                    DAEMON_URI,
                    max_size=10 * 1024 * 1024,
                    ping_interval=20,
                    ping_timeout=10,
                    open_timeout=10,
                ) as ws:
                    # Register on the /inference path (daemon expects this as first frame)
                    await ws.send(REGISTRATION_FRAME)
                    logger.info("Registered on /inference path with daemon.")

                    # Start background context loop; cancel it when WS closes
                    ctx_task = asyncio.ensure_future(self._context_loop(ws))
                    try:
                        async for raw in ws:
                            await self._dispatch(raw, ws)
                    finally:
                        ctx_task.cancel()
                        try:
                            await ctx_task
                        except asyncio.CancelledError:
                            pass

            except (OSError, websockets.exceptions.WebSocketException) as exc:
                logger.warning("Daemon connection lost (%s). Reconnecting in %.0fs…",
                               exc, RECONNECT_DELAY)
                await asyncio.sleep(RECONNECT_DELAY)
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected error in run loop: %s", exc, exc_info=True)
                await asyncio.sleep(RECONNECT_DELAY)

    async def _dispatch(self, raw: str, ws: Any) -> None:
        """Parse an incoming JSON message and route to the appropriate handler.
        
        Handles both:
        - Rust serde(tag,content) format: {"type": "NewCapture", "payload": {...}}
        - Simple format: {"type": "ping"}
        """
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON from daemon: %s", exc)
            return

        msg_type = msg.get("type", "")
        # serde(tag="type", content="payload") wraps everything under "payload"
        payload = msg.get("payload", msg)  # fall back to the message itself if no payload

        try:
            # Messages FROM the daemon to the inference engine
            if msg_type == "NewCapture":
                await self.process_capture(payload, ws)
            elif msg_type == "TabContext":
                self.handle_tab_context(payload)
            elif msg_type == "UserFeedback":
                self._handle_feedback(payload)
            # Legacy / direct formats (for testing without daemon)
            elif msg_type == "capture":
                await self.process_capture(payload, ws)
            elif msg_type == "tab_context":
                self.handle_tab_context(payload)
            elif msg_type == "feedback":
                self._handle_feedback(payload)
            elif msg_type == "ping":
                await self._send(ws, {"type": "pong"})
            else:
                logger.debug("Unhandled message type from daemon: %s", msg_type)
        except Exception as exc:  # noqa: BLE001
            logger.error("dispatch error for type=%s: %s", msg_type, exc, exc_info=True)

    # ------------------------------------------------------------------
    # Capture processing
    # ------------------------------------------------------------------

    async def process_capture(self, capture: Dict[str, Any], ws: Any) -> None:
        """
        Run Tier-1 NLP on an incoming capture, compute scores, persist, respond.

        Parameters
        ----------
        capture : dict
            Fields from the browser extension.  Must include at least
            'markdown' or 'content' and optionally 'user_note', 'source_url',
            'title', 'domain', 'capture_id'.
        ws : WebSocketServerProtocol
            The client connection to acknowledge.
        """
        # Ensure we have a capture_id
        capture_id = capture.get("capture_id") or str(uuid.uuid4())
        capture["capture_id"] = capture_id

        markdown = capture.pop("content_markdown", capture.pop("markdown", capture.pop("content", "")))
        user_note = capture.get("user_note", "")
        domain = capture.get("domain", "")
        if not domain and capture.get("source_url"):
            try:
                from urllib.parse import urlparse
                parsed = urlparse(capture["source_url"])
                domain = parsed.hostname or parsed.scheme or ""
            except Exception:
                domain = ""
            capture["domain"] = domain

        is_empty_markdown = not markdown or not markdown.strip()
        extraction_failed = 1 if is_empty_markdown else 0

        logger.info("Processing capture %s (%d chars markdown, extraction_failed=%d)", 
                    capture_id, len(markdown), extraction_failed)

        # ---- Run Tier-1 NLP ----
        nlp_result = {
            "keywords_yake": [],
            "named_entities": [],
            "noun_phrases": [],
            "embedding_vector": [0.0] * 384,
            "note_embedding": [0.0] * 384,
        }
        pe_score = 0.0
        reliability = 0.5
        emphasis = 0.0

        if not is_empty_markdown:
            loop = asyncio.get_event_loop()
            try:
                nlp_result = await loop.run_in_executor(
                    None, lambda: self.nlp.process(markdown, user_note)
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Tier-1 processing failed: %s", exc)

            # ---- Prediction-error score (semantic novelty) ----
            embedding_vector = nlp_result.get("embedding_vector", [0.0] * 384)
            try:
                all_embeddings = self.storage.get_all_embeddings()
                pe_score = await loop.run_in_executor(
                    None,
                    lambda: self.nlp.prediction_error_score(embedding_vector, all_embeddings),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("prediction_error_score failed: %s", exc)
                pe_score = 0.5

            # ---- Heuristic scores ----
            reliability = self.nlp.source_reliability(domain)
            emphasis = self.nlp.user_emphasis(user_note)
        else:
            emphasis = self.nlp.user_emphasis(user_note)

        # ---- Auto-title generation (eliminates "Untitled" records) ----
        title = capture.get("title", "")
        source_url = capture.get("source_url", "")
        auto_title = ""
        if not title or title.strip() == "" or title.strip().lower() == "untitled":
            auto_title = self.nlp.generate_auto_title(
                nlp_result, markdown=markdown, source_url=source_url,
            )
            logger.info("Auto-title generated: '%s'", auto_title)

        # ---- Pramāṇa epistemic classification ----
        content_type = capture.get("content_type", "")
        epistemic_type = self.nlp.classify_epistemic_type(
            source_url=source_url,
            user_note=user_note,
            content_type=content_type,
            has_markdown=bool(markdown and len(markdown) > 10),
        )
        logger.info("Epistemic type: %s", epistemic_type)

        # ---- Build persist record ----
        import json as _json  # already imported at top but alias for clarity

        record = {
            **capture,
            "capture_id": capture_id,
            "timestamp": capture.get("timestamp", time.time()),
            "title": title if (title and title.strip() and title.strip().lower() != "untitled") else None,
            "auto_title": auto_title if auto_title else None,
            "epistemic_type": epistemic_type,
            "content_markdown": markdown,
            "excerpt": capture.get("excerpt") or (markdown[:200] if markdown else ""),
            "keywords_json": json.dumps(nlp_result.get("keywords_yake", [])),
            "entities_json": json.dumps(nlp_result.get("named_entities", [])),
            "noun_phrases_json": json.dumps(nlp_result.get("noun_phrases", [])),
            "prediction_error_score": pe_score,
            "semantic_novelty": pe_score,
            "user_emphasis": emphasis,
            "source_reliability": reliability,
            "tier1_processed_at": time.time(),
            "embedding": np.array(nlp_result.get("embedding_vector", [0.0]*384), dtype=np.float32),
            "extraction_failed": extraction_failed,
        }

        try:
            self.storage.save_capture(record)
            logger.info(
                "Capture %s saved. PE=%.3f reliability=%.2f emphasis=%.2f type=%s title='%s'",
                capture_id, pe_score, reliability, emphasis,
                epistemic_type, title or auto_title,
            )
            
            # Asynchronously update topic clustering and export to Obsidian
            loop = asyncio.get_event_loop()
            
            # Re-run topic clustering
            await loop.run_in_executor(None, run_kmeans_clustering, self.storage)
            
            # Find similar captures for Obsidian link mapping
            similar_candidates = self.storage.find_similar_captures(record["embedding"], limit=10)
            strong_matches = [
                c for c in similar_candidates 
                if c.get("score", 0.0) > 0.82 and c.get("capture_id") != capture_id
            ]
            
            # Export to local Obsidian vault
            await loop.run_in_executor(None, export_to_obsidian, record, strong_matches)
            
        except Exception as exc:  # noqa: BLE001
            logger.error("save_capture or post-processing failed: %s", exc)

        await self._send(ws, {"type": "ack", "capture_id": capture_id})

    # ------------------------------------------------------------------
    # Tab context handler
    # ------------------------------------------------------------------

    def handle_tab_context(self, payload: Dict[str, Any]) -> None:
        """Update ContextMonitor with the new active tab."""
        url = payload.get("url", "")
        title = payload.get("title", "")
        self.context_monitor.set_tab_context(url, title)

    # ------------------------------------------------------------------
    # Feedback handler
    # ------------------------------------------------------------------

    def _handle_feedback(self, payload: Dict[str, Any]) -> None:
        """Update agent beliefs from user feedback and log the event."""
        capture_id = payload.get("capture_id", "")
        action = payload.get("action", "ignored")
        duration_ms = int(payload.get("duration_ms", 0))
        inferred_topic = self._last_inference.get("inferred_topic", 0)

        # Log to storage
        try:
            self.storage.log_resurface_event(
                capture_id=capture_id,
                action=action,
                efe_score=0.0,   # EFE not persisted at feedback time
                context_similarity=0.0,
                inferred_topic=inferred_topic,
                duration_visible_ms=duration_ms,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("log_resurface_event failed: %s", exc)

        # Update agent
        try:
            self.agent.process_feedback(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("process_feedback failed: %s", exc)

        logger.info("Feedback: %s on %s (%.0f ms)", action, capture_id, duration_ms)

    # ------------------------------------------------------------------
    # Context loop
    # ------------------------------------------------------------------

    # (context_loop is now an instance method started per-connection in run())

    async def _context_loop(self, ws: Any) -> None:
        """Periodically run inference and send ResurfaceSignal to daemon if warranted."""
        while True:
            await asyncio.sleep(CONTEXT_LOOP_INTERVAL)
            try:
                await self._run_context_cycle(ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.debug("Context cycle error: %s", exc)

    async def _run_context_cycle(self, ws: Any) -> None:
        """
        Single iteration of the active-inference / resurface loop.

        1. Get current observation from ContextMonitor
        2. Run CorteonAgent.inference_step
        3. If resurface_action != 0, find candidates and send resurface message
        """
        loop = asyncio.get_event_loop()

        # Get observation (potentially triggers embedding — run in executor)
        try:
            obs_dict = await loop.run_in_executor(
                None, self.context_monitor.get_current_observation
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_current_observation failed: %s", exc)
            return

        obs_tuple = (
            int(obs_dict.get("context_obs", 0)),
            int(obs_dict.get("capture_obs", 0)),
            int(obs_dict.get("temporal_obs", 1)),
            int(obs_dict.get("feedback_obs", 0)),
        )

        # Run inference
        try:
            inference_result = self.agent.inference_step(obs_tuple)
            self._last_inference = inference_result
        except Exception as exc:  # noqa: BLE001
            logger.error("inference_step failed: %s", exc)
            return

        resurface_action  = inference_result.get("resurface_action", 0)
        display_intensity = inference_result.get("display_intensity", 0)
        inferred_topic    = inference_result.get("inferred_topic", 0)
        inferred_need     = inference_result.get("inferred_need", "Idle")

        logger.debug(
            "Inference: action=%d display=%d topic=%d need=%s",
            resurface_action, display_intensity, inferred_topic, inferred_need,
        )

        if resurface_action == 0:
            return  # agent decided not to resurface anything

        # Cooldown check to prevent overlay flickering repeatedly
        now = time.time()
        if now - self._last_resurface_time < RESURFACE_COOLDOWN:
            logger.debug(
                "Resurfacing suppressed due to cooldown (%.1fs remaining)",
                RESURFACE_COOLDOWN - (now - self._last_resurface_time)
            )
            return

        # Fetch resurface candidates
        try:
            context_embedding = obs_dict.get("context_embedding")
            if context_embedding is not None and isinstance(context_embedding, np.ndarray):
                # Retrieve 20 candidates for ranking (retrieve-then-rank)
                candidates = self.storage.find_similar_captures(
                    context_embedding, limit=20
                )
                
                scored_candidates = []
                for c in candidates:
                    cid = c["capture_id"]
                    # Get candidate embedding from storage to calculate redundancy penalty
                    emb_row = self.storage.conn.execute(
                        "SELECT embedding FROM embeddings WHERE capture_id = ?", (cid,)
                    ).fetchone()
                    
                    penalty = 0.0
                    if emb_row is not None:
                        from storage import _blob_to_array
                        candidate_emb = _blob_to_array(emb_row["embedding"])
                        penalty = self.context_monitor.get_redundancy_penalty(candidate_emb)
                        
                    # Resolve need-state weights
                    weights = {
                        "seeking": (0.3, 0.7, 0.5),
                        "processing": (0.8, 0.2, 0.1),
                        "synthesizing": (0.5, 0.5, 0.3),
                        "idle": (0.5, 0.5, 0.3),
                    }
                    w_sim, w_diff, w_redundancy = weights.get(
                        inferred_need.lower().strip(), weights["synthesizing"]
                    )
                    
                    # Calculate concept divergence (silo-breaking check)
                    topic_a = inferred_topic
                    topic_b = c.get("topic_cluster_id")
                    divergence = 1.0 if topic_b is None or topic_a != topic_b else 0.0
                    
                    cosine_sim = float(c.get("score", 0.0))
                    adaptive_score = (w_sim * cosine_sim) + (w_diff * divergence) - (w_redundancy * penalty)
                    
                    c["original_score"] = cosine_sim
                    c["score"] = adaptive_score
                    scored_candidates.append(c)
                
                scored_candidates.sort(key=lambda x: x["score"], reverse=True)
                candidates = scored_candidates
            else:
                candidates = self.storage.get_resurface_candidates(
                    topic_id=inferred_topic if inferred_topic < 8 else None,
                    limit=MAX_RESURFACE_CANDIDATES,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch resurface candidates: %s", exc)
            candidates = []

        if not candidates:
            return

        # Calculate adaptive threshold: tau_high = tau_base * (1.0 + beta * topic_entropy)
        topic_entropy = inference_result.get("topic_entropy", 0.0)
        tau_base = 0.45
        beta = 0.5
        tau_high = tau_base * (1.0 + beta * topic_entropy)
        
        top_cand = candidates[0]
        top_score = float(top_cand.get("score", 0.0))
        
        logger.info(
            "Top candidate adaptive score: %.3f (threshold: %.3f, entropy: %.2f)",
            top_score, tau_high, topic_entropy
        )
        
        if top_score < tau_high:
            logger.debug(
                "Resurfacing suppressed: top score %.3f below threshold %.3f",
                top_score, tau_high
            )
            return

        # Filter based on resurface action strategy
        if resurface_action == 2:  # high_PE: prefer semantically novel items
            candidates.sort(
                key=lambda c: float(c.get("prediction_error_score", 0)), reverse=True
            )

        # Strip large/binary fields before sending
        safe_candidates = []
        for c in candidates[:MAX_RESURFACE_CANDIDATES]:
            safe_candidates.append({
                "capture_id":        c.get("capture_id", ""),
                "title":             c.get("title", ""),
                "source_url":        c.get("source_url", ""),
                "one_sentence_summary": c.get("one_sentence_summary", ""),
                "keywords_json":     c.get("keywords_json", "[]"),
                "prediction_error_score": float(c.get("prediction_error_score", 0)),
                "topic_cluster_id":  c.get("topic_cluster_id"),
                "score":             float(c.get("score", 0)),
            })

        # Log the resurface decision
        for c in safe_candidates[:1]:  # log top candidate
            try:
                ctx_sim = float(c.get("score", 0))
                self.storage.log_resurface_event(
                    capture_id=c["capture_id"],
                    action=f"resurface_action_{resurface_action}",
                    efe_score=0.0,
                    context_similarity=ctx_sim,
                    inferred_topic=inferred_topic,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("log_resurface_event failed: %s", exc)

        # Send ResurfaceSignal to daemon (daemon relays to UI)
        # Use the Rust serde(tag,content) format: {type, payload}
        top = safe_candidates[0]
        title = top.get("title") or top.get("auto_title") or top.get("source_url") or "Captured Note"
        excerpt = top.get("one_sentence_summary") or top.get("excerpt") or ""
        msg = {
            "type": "ResurfaceSignal",
            "payload": {
                "capture_id":      top["capture_id"],
                "title":           title,
                "excerpt":         excerpt,
                "user_note":       top.get("user_note"),
                "relevance_score": float(top.get("score", 0.0)),
                "efe_score":       0.0,
                "display_intensity": float(display_intensity),
                "reason":          f"Topic {inferred_topic} • Need: {inferred_need}",
            },
        }
        await self._send(ws, msg)
        self._last_resurface_time = now
        logger.info(
            "ResurfaceSignal sent to daemon: action=%d display=%d %d candidates",
            resurface_action, display_intensity, len(safe_candidates),
        )

    # ------------------------------------------------------------------
    # WebSocket send helper
    # ------------------------------------------------------------------

    @staticmethod
    async def _send(ws: Any, data: Dict[str, Any]) -> None:
        """Serialise *data* to JSON and send it, ignoring closed-connection errors."""
        try:
            await ws.send(json.dumps(data))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_send failed (client likely disconnected): %s", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the Calm Capture inference engine."""
    logger.info("Calm Capture Inference Engine starting…")
    try:
        asyncio.run(InferenceEngine().run())
    except KeyboardInterrupt:
        logger.info("Inference engine stopped by user.")


if __name__ == "__main__":
    main()
