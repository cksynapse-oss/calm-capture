import struct
import json
import time
import logging
from collections import Counter
from typing import Any, Dict, List
import numpy as np

logger = logging.getLogger("clustering")

def run_kmeans_clustering(storage: Any, n_clusters: int = 8) -> None:
    """
    Run K-Means clustering (using Cosine similarity / dot-product of normalized vectors)
    on all stored captures, then upsert centroids and update capture topic_cluster_ids.
    
    If there are fewer than n_clusters unique embeddings, falls back to metadata/hash-based grouping
    to ensure captures are distributed across clusters for visualization and UI purposes.
    """
    try:
        # 1. Fetch all captures and embeddings
        rows = storage.conn.execute(
            "SELECT c.capture_id, c.title, c.auto_title, c.keywords_json, c.user_note, e.embedding "
            "FROM captures c "
            "JOIN embeddings e ON c.capture_id = e.capture_id"
        ).fetchall()
        
        if not rows:
            logger.info("No captures found in DB. Skipping clustering.")
            return

        # Parse embeddings and metadata
        def _blob_to_array(blob: bytes) -> np.ndarray:
            n = len(blob) // 4
            return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)

        X = []
        captures = []
        for r in rows:
            try:
                emb = _blob_to_array(r["embedding"])
                X.append(emb)
            except Exception:
                X.append(np.zeros(384, dtype=np.float32))
                
            kws = []
            kw_raw = r["keywords_json"]
            if kw_raw:
                try:
                    parsed = json.loads(kw_raw)
                    if parsed:
                        if isinstance(parsed, list):
                            if isinstance(parsed[0], list):
                                kws = [item[0] for item in parsed]
                            else:
                                kws = parsed
                except Exception:
                    pass
            
            captures.append({
                "capture_id": r["capture_id"],
                "title": r["title"] or r["auto_title"] or "Captured Note",
                "keywords": kws,
                "user_note": r["user_note"] or ""
            })

        X = np.array(X, dtype=np.float32)
        N = len(X)
        
        # Check number of unique embeddings
        unique_embs = []
        for e in X:
            if not any(np.allclose(e, u, atol=1e-4) for u in unique_embs):
                unique_embs.append(e)
                
        num_unique = len(unique_embs)
        logger.info("Clustering %d captures (%d unique embeddings) into %d clusters.", N, num_unique, n_clusters)
        
        assignments = np.zeros(N, dtype=int)
        
        if num_unique < n_clusters:
            # Fallback grouping: assign based on capture_id hash to distribute them
            logger.info("Fewer than %d unique embeddings. Using fallback hash-based grouping to distribute topics.", n_clusters)
            for i, cap in enumerate(captures):
                h = hash(cap["capture_id"])
                assignments[i] = abs(h) % n_clusters
                
            centroids = np.zeros((n_clusters, 384), dtype=np.float32)
            base_emb = unique_embs[0] if num_unique > 0 else np.zeros(384, dtype=np.float32)
            for k in range(n_clusters):
                centroids[k] = base_emb.copy()
                centroids[k][k % 384] += 0.1
                norm = np.linalg.norm(centroids[k])
                if norm > 0:
                    centroids[k] /= norm
        else:
            # Standard K-Means using Cosine Similarity
            norms = np.linalg.norm(X, axis=1, keepdims=True)
            X = np.where(norms > 0, X / norms, X)
            
            # Initialize centroids randomly with a fixed seed
            np.random.seed(42)
            random_indices = np.random.choice(N, n_clusters, replace=False)
            centroids = X[random_indices].copy()
            
            for iteration in range(100):
                similarities = np.dot(X, centroids.T)
                new_assignments = np.argmax(similarities, axis=1)
                
                if np.array_equal(assignments, new_assignments):
                    break
                assignments = new_assignments
                
                # Update centroids
                for k in range(n_clusters):
                    mask = (assignments == k)
                    if np.any(mask):
                        centroids[k] = np.mean(X[mask], axis=0)
                        c_norm = np.linalg.norm(centroids[k])
                        if c_norm > 0:
                            centroids[k] /= c_norm
                    else:
                        centroids[k] = X[np.random.choice(N)]

        # 3. Compute semantic labels and upsert clusters
        for k in range(n_clusters):
            cluster_indices = np.where(assignments == k)[0]
            count = len(cluster_indices)
            
            all_kw = []
            for idx in cluster_indices:
                all_kw.extend(captures[idx]["keywords"])
                
            # Filter unhelpful words
            filtered_kw = [
                w.lower() for w in all_kw 
                if len(w) > 2 and w.lower() not in ["none", "null", "page", "note", "captured"]
            ]
            
            most_common = Counter(filtered_kw).most_common(3)
            if most_common:
                label = " • ".join([w[0].title() for w in most_common])
            else:
                default_labels = [
                    "Research & Epistemology",
                    "Cognitive Systems",
                    "Computational Neuroscience",
                    "Philosophy & Indian Logic",
                    "Active Inference & Free Energy",
                    "Sensorimotor Systems",
                    "Neuromorphic Computing",
                    "Productivity & Knowledge Graphs"
                ]
                label = default_labels[k]
                
            centroid = centroids[k]
            
            # Save cluster to database
            storage.upsert_topic_cluster(
                cluster_id=k,
                label=label,
                centroid=centroid,
                capture_count=count
            )
            logger.debug("Upserted cluster %d: label='%s', count=%d", k, label, count)
            
        # 4. Update captures with their assigned topic cluster id
        for i, cap in enumerate(captures):
            storage.update_capture_cluster(cap["capture_id"], int(assignments[i]))
            
        logger.info("Successfully updated cluster assignments for all %d captures.", N)

    except Exception as e:
        logger.error("run_kmeans_clustering failed: %s", e, exc_info=True)
