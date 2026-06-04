import os
import re
import datetime
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("obsidian_exporter")

VAULT_DIR = Path.home() / "CalmCaptureVault"

def sanitize_filename(title: str) -> str:
    """
    Remove characters that are invalid in file systems and Obsidian wiki-links.
    """
    if not title:
        return "Untitled Note"
    # Replace characters: \ / * ? : " < > | # ^ [ ] with empty string or space
    sanitized = re.sub(r'[\\/*?:"<>|#\^\[\]]', '', title)
    return sanitized.strip()[:100]  # Limit length for filesystem safety

def export_to_obsidian(capture: Dict[str, Any], similar_captures: List[Dict[str, Any]]) -> None:
    """
    Export a single capture as a Markdown file with YAML frontmatter in the Obsidian Vault.
    Guarantees unique filenames using the capture ID.
    """
    try:
        VAULT_DIR.mkdir(parents=True, exist_ok=True)
        
        title = capture.get("title") or capture.get("auto_title") or "Captured Note"
        capture_id = capture.get("capture_id", "unknown")
        sanitized_title = sanitize_filename(title)
        
        # Append short capture ID to guarantee uniqueness and prevent files overwriting each other
        file_path = VAULT_DIR / f"{sanitized_title} ({capture_id[:8]}).md"
        
        # Generate related wiki links matching the filename structure
        related_links = []
        for sim in similar_captures:
            sim_title = sim.get("title") or sim.get("auto_title") or "Captured Note"
            sim_cid = sim.get("capture_id", "")
            sim_sanitized = sanitize_filename(sim_title)
            score = sim.get("score", 0.0)
            related_links.append(f"- [[{sim_sanitized} ({sim_cid[:8]})]] (Similarity: {int(score * 100)}%)")
            
        related_section = "\n".join(related_links) if related_links else "No strongly related concepts found yet."
        
        # Parse timestamp
        try:
            ts = float(capture.get("timestamp", 0))
            date_str = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
        content = f"""---
id: "{capture_id}"
date: "{date_str}"
url: "{capture.get('source_url', '') or ''}"
domain: "{capture.get('domain', '') or ''}"
epistemic_type: "{capture.get('epistemic_type', 'pratyaksa')}"
prediction_error_score: {capture.get('prediction_error_score', 0.0)}
---
# {title}

## Auto Summary
{capture.get('one_sentence_summary') or capture.get('excerpt') or 'No summary available.'}

## Full Capture Content
{capture.get('content_markdown') or 'No content text captured.'}

## Reflection Notes
{capture.get('user_note') or 'No reflection notes added yet.'}

## Related Concepts (Calm Capture Similarity)
{related_section}
"""
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
            
    except Exception as e:
        logger.warning("Failed to export capture %s to Obsidian: %s", capture.get('capture_id'), e)

def sync_all_captures_to_obsidian(storage: Any) -> None:
    """
    Regenerate all Markdown files in the Obsidian vault from current SQLite database data.
    """
    try:
        VAULT_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Syncing captures to Obsidian Vault at %s", VAULT_DIR)
        
        # Clean up any existing markdown files to prevent stale nodes if titles/IDs changed
        for f in VAULT_DIR.glob("*.md"):
            try:
                f.unlink()
            except Exception:
                pass
        
        # Get all captures
        rows = storage.conn.execute("SELECT * FROM captures").fetchall()
        captures = [dict(r) for r in rows]
        
        # Get all embeddings
        all_embs = storage.get_all_embeddings()
        emb_dict = {item["capture_id"]: item["embedding"] for item in all_embs}
        
        # Import cosine similarity helper
        from storage import _cosine_similarity
        
        # Export each capture with its similarity connections
        for cap in captures:
            cid = cap["capture_id"]
            similar_captures = []
            
            if cid in emb_dict:
                my_emb = emb_dict[cid]
                # Compare against all other embeddings
                for other_cid, other_emb in emb_dict.items():
                    if other_cid != cid:
                        sim = _cosine_similarity(my_emb, other_emb)
                        if sim > 0.82:  # Threshold matching active graph
                            other_cap = next((c for c in captures if c["capture_id"] == other_cid), None)
                            if other_cap:
                                similar_captures.append({
                                    "capture_id": other_cid,
                                    "title": other_cap.get("title") or other_cap.get("auto_title"),
                                    "score": sim
                                })
                                
            # Sort by similarity descending
            similar_captures.sort(key=lambda x: x["score"], reverse=True)
            export_to_obsidian(cap, similar_captures)
            
        logger.info("Successfully synced %d files to Obsidian Vault.", len(captures))
        
    except Exception as e:
        logger.warning("sync_all_captures_to_obsidian failed: %s", e)
