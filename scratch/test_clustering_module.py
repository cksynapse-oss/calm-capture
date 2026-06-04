import sqlite3
from pathlib import Path
import sys

# Add inference directory to path
sys.path.append("/Users/hahaha/Desktop/untitled folder/calm-capture/inference")

from storage import CorteonStorage
from clustering import run_kmeans_clustering

storage = CorteonStorage()

print("Running K-Means clustering...")
run_kmeans_clustering(storage)

# Verify table contents
conn = storage.conn
clusters = conn.execute("SELECT * FROM topic_clusters").fetchall()
print(f"Topic clusters updated: {len(clusters)} rows found.")
for c in clusters:
    print(f"  Cluster {c['cluster_id']}: label='{c['label']}', count={c['capture_count']}")

cluster_counts = conn.execute("SELECT topic_cluster_id, count(*) as cnt FROM captures GROUP BY topic_cluster_id").fetchall()
print("Capture counts per cluster:")
for r in cluster_counts:
    print(f"  Cluster {r['topic_cluster_id']}: {r['cnt']}")

storage.close()
