import json
import logging
from typing import Any, Dict, List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import numpy as np

from storage import CorteonStorage, _cosine_similarity

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Calm Capture Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

storage = CorteonStorage()

# ---------------------------------------------------------------------------
# Precision threshold for graph edges (Active Inference precision weighting)
# ---------------------------------------------------------------------------
SIMILARITY_THRESHOLD = 0.82


@app.get("/api/captures")
def get_captures() -> List[Dict[str, Any]]:
    """Returns all captures ordered by timestamp."""
    rows = storage.conn.execute(
        "SELECT * FROM captures ORDER BY timestamp DESC"
    ).fetchall()
    
    result = []
    for row in rows:
        d = dict(row)
        # Parse JSON fields for easier frontend consumption
        for field in ["keywords_json", "entities_json", "noun_phrases_json", "concepts_json"]:
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except Exception:
                    d[field] = []
        result.append(d)
    return result


class NoteUpdate(BaseModel):
    user_note: str


@app.post("/api/captures/{capture_id}/note")
def update_capture_note(capture_id: str, note_data: NoteUpdate):
    """Updates the user note for a specific capture."""
    with storage.conn:
        storage.conn.execute(
            "UPDATE captures SET user_note = ? WHERE capture_id = ?",
            (note_data.user_note, capture_id)
        )
    return {"success": True}


def _compute_edge_label(kw_a: list, kw_b: list) -> str:
    """Find shared keywords between two captures to label the edge."""
    if not kw_a or not kw_b:
        return ""
    set_a = {k.lower() for k in kw_a if isinstance(k, str)}
    set_b = {k.lower() for k in kw_b if isinstance(k, str)}
    shared = set_a & set_b
    if shared:
        return sorted(shared, key=len, reverse=True)[0].title()
    return ""


@app.get("/api/graph")
def get_graph(threshold: float = 0.82) -> Dict[str, Any]:
    """
    Returns graph data: nodes (captures) and links (similarities > threshold).
    
    Nodes include Pramāṇa epistemic_type and auto-generated titles.
    Edges are precision-thresholded at the provided threshold and labeled
    with shared keywords where available.
    """
    captures = get_captures()
    nodes = []
    kw_map = {}  # capture_id → keywords list for edge labeling
    
    for c in captures:
        cid = c["capture_id"]
        # Resolve display title: title → auto_title → domain → "Captured Note"
        display_title = (
            c.get("title")
            or c.get("auto_title")
            or c.get("source_url")
            or "Captured Note"
        )
        
        # Parse keywords for edge labeling
        kw_raw = c.get("keywords_json", [])
        if isinstance(kw_raw, str):
            try:
                kw_raw = json.loads(kw_raw)
            except Exception:
                kw_raw = []
        kw_map[cid] = kw_raw if isinstance(kw_raw, list) else []
        
        nodes.append({
            "id": cid,
            "title": display_title,
            "group": c.get("topic_cluster_id", 0),
            "novelty": c.get("prediction_error_score", 0.0),
            "domain": c.get("domain", ""),
            "epistemic_type": c.get("epistemic_type", "pratyaksa"),
            "user_note": c.get("user_note", ""),
        })
    
    # Get all embeddings to compute edges
    all_embs = storage.get_all_embeddings()
    emb_dict = {item["capture_id"]: item["embedding"] for item in all_embs}
    
    links = []
    capture_ids = [c["capture_id"] for c in captures if c["capture_id"] in emb_dict]
    
    for i in range(len(capture_ids)):
        for j in range(i + 1, len(capture_ids)):
            id1 = capture_ids[i]
            id2 = capture_ids[j]
            sim = _cosine_similarity(emb_dict[id1], emb_dict[id2])
            if sim > threshold:
                label = _compute_edge_label(
                    kw_map.get(id1, []),
                    kw_map.get(id2, [])
                )
                links.append({
                    "source": id1,
                    "target": id2,
                    "value": round(sim, 3),
                    "label": label,
                })
                
    return {
        "nodes": nodes,
        "links": links,
        "meta": {
            "threshold": threshold,
            "node_count": len(nodes),
            "edge_count": len(links),
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)

