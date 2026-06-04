#!/usr/bin/env python3
"""
One-off database purge script for corteon.db.
Removes corrupted rows:
  1. extraction_failed = 1
  2. content_markdown is NULL or empty string
  3. Orphaned embeddings with no matching capture
Also prints before/after stats.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".corteon" / "corteon.db"

def main():
    if not DB_PATH.exists():
        print(f"❌ Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # --- Before stats ---
    total_captures = conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
    total_embeddings = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    
    failed_count = conn.execute(
        "SELECT COUNT(*) FROM captures WHERE extraction_failed = 1"
    ).fetchone()[0]
    
    empty_md_count = conn.execute(
        "SELECT COUNT(*) FROM captures WHERE content_markdown IS NULL OR content_markdown = ''"
    ).fetchone()[0]
    
    # Check for rows with empty title AND empty auto_title (likely garbage)
    empty_title_count = conn.execute(
        "SELECT COUNT(*) FROM captures WHERE (title IS NULL OR title = '' OR title = 'Untitled') AND (auto_title IS NULL OR auto_title = '')"
    ).fetchone()[0]

    print("=" * 60)
    print("  CALM CAPTURE — DATABASE PURGE")
    print("=" * 60)
    print(f"\n📊 BEFORE:")
    print(f"   Total captures:        {total_captures}")
    print(f"   Total embeddings:      {total_embeddings}")
    print(f"   extraction_failed=1:   {failed_count}")
    print(f"   Empty markdown:        {empty_md_count}")
    print(f"   Empty/Untitled titles: {empty_title_count}")
    
    # --- Purge ---
    # 1. Delete captures where extraction failed
    cursor = conn.execute(
        "DELETE FROM captures WHERE extraction_failed = 1"
    )
    deleted_failed = cursor.rowcount
    
    # 2. Delete captures with empty markdown
    cursor = conn.execute(
        "DELETE FROM captures WHERE content_markdown IS NULL OR content_markdown = ''"
    )
    deleted_empty = cursor.rowcount
    
    # 3. Clean orphaned embeddings
    cursor = conn.execute(
        "DELETE FROM embeddings WHERE capture_id NOT IN (SELECT capture_id FROM captures)"
    )
    deleted_orphan_emb = cursor.rowcount
    
    # 4. Clean orphaned resurface events
    cursor = conn.execute(
        "DELETE FROM resurface_events WHERE capture_id NOT IN (SELECT capture_id FROM captures)"
    )
    deleted_orphan_events = cursor.rowcount
    
    conn.commit()
    
    # --- After stats ---
    remaining_captures = conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
    remaining_embeddings = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    remaining_events = conn.execute("SELECT COUNT(*) FROM resurface_events").fetchone()[0]
    
    print(f"\n🧹 PURGED:")
    print(f"   Extraction-failed captures: {deleted_failed}")
    print(f"   Empty-markdown captures:    {deleted_empty}")
    print(f"   Orphaned embeddings:        {deleted_orphan_emb}")
    print(f"   Orphaned resurface events:  {deleted_orphan_events}")
    
    print(f"\n✅ AFTER:")
    print(f"   Remaining captures:    {remaining_captures}")
    print(f"   Remaining embeddings:  {remaining_embeddings}")
    print(f"   Remaining events:      {remaining_events}")
    
    # --- Show surviving records summary ---
    if remaining_captures > 0:
        print(f"\n📋 SURVIVING CAPTURES:")
        rows = conn.execute(
            "SELECT capture_id, title, auto_title, domain, epistemic_type, prediction_error_score, extraction_failed "
            "FROM captures ORDER BY timestamp DESC LIMIT 20"
        ).fetchall()
        for r in rows:
            title = r["title"] or r["auto_title"] or "(no title)"
            etype = r["epistemic_type"] or "pratyaksa"
            pe = r["prediction_error_score"] or 0.0
            print(f"   • [{etype:10s}] {title[:50]:50s} PE={pe:.2f}  domain={r['domain'] or '-'}")
    
    # --- VACUUM to reclaim space ---
    conn.execute("VACUUM")
    conn.close()
    print(f"\n🗜️  Database vacuumed. Clean slate ready.")
    print("=" * 60)

if __name__ == "__main__":
    main()
