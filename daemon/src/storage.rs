use anyhow::{Context, Result};
use rusqlite::{params, Connection};
use std::path::Path;

// ---------------------------------------------------------------------------
// Row types returned from queries
// ---------------------------------------------------------------------------

/// A row from the `captures` table.
#[derive(Debug, Clone)]
pub struct CaptureRow {
    pub capture_id: String,
    pub timestamp: String,
    pub title: String,
    pub source_url: String,
    pub content_markdown: String,
    pub byline: Option<String>,
    pub excerpt: String,
    pub word_count: u32,
    pub prediction_error_score: f64,
    pub user_note: Option<String>,
    pub topic_cluster_id: Option<String>,
    pub created_at: String,
}

/// A row from the `resurface_events` table.
#[derive(Debug, Clone)]
pub struct ResurfaceEventRow {
    pub event_id: String,
    pub capture_id: String,
    pub action: String,
    pub efe_score: f64,
    pub context_similarity: f64,
    pub occurred_at: String,
}

// ---------------------------------------------------------------------------
// Storage handle
// ---------------------------------------------------------------------------

/// Thin wrapper around a `rusqlite::Connection` providing all persistence
/// operations required by the Corteon daemon.
pub struct Storage {
    conn: Connection,
}

impl Storage {
    /// Open (or create) the database at `db_path` and ensure all tables exist.
    pub fn new<P: AsRef<Path>>(db_path: P) -> Result<Self> {
        let conn = Connection::open(db_path.as_ref())
            .with_context(|| format!("opening database at {}", db_path.as_ref().display()))?;

        // Enable WAL mode for better concurrent read performance.
        conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")
            .context("setting database pragmas")?;

        let storage = Storage { conn };
        storage.create_tables()?;
        Ok(storage)
    }

    // -----------------------------------------------------------------------
    // Schema
    // -----------------------------------------------------------------------

    /// Create all tables if they do not yet exist.
    /// The schema is intentionally kept in sync with the Python inference layer.
    pub fn create_tables(&self) -> Result<()> {
        self.conn
            .execute_batch(
                r#"
                -- Topic clusters produced by the inference engine
                CREATE TABLE IF NOT EXISTS topic_clusters (
                    cluster_id   TEXT PRIMARY KEY,
                    label        TEXT NOT NULL,
                    centroid_json TEXT NOT NULL,           -- JSON array of floats
                    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
                );

                -- One row per captured article
                CREATE TABLE IF NOT EXISTS captures (
                    capture_id            TEXT PRIMARY KEY,
                    timestamp             TEXT NOT NULL,
                    title                 TEXT NOT NULL,
                    source_url            TEXT NOT NULL,
                    content_markdown      TEXT NOT NULL,
                    byline                TEXT,
                    excerpt               TEXT NOT NULL,
                    word_count            INTEGER NOT NULL DEFAULT 0,
                    prediction_error_score REAL NOT NULL DEFAULT 0.0,
                    user_note             TEXT,
                    topic_cluster_id      TEXT REFERENCES topic_clusters(cluster_id),
                    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
                );

                CREATE INDEX IF NOT EXISTS idx_captures_created_at
                    ON captures (created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_captures_cluster
                    ON captures (topic_cluster_id);

                -- One row per time a capture was surfaced to the user
                CREATE TABLE IF NOT EXISTS resurface_events (
                    event_id           TEXT PRIMARY KEY,
                    capture_id         TEXT NOT NULL REFERENCES captures(capture_id),
                    action             TEXT NOT NULL,   -- 'clicked' | 'dismissed' | 'ignored'
                    efe_score          REAL NOT NULL DEFAULT 0.0,
                    context_similarity REAL NOT NULL DEFAULT 0.0,
                    occurred_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
                );

                CREATE INDEX IF NOT EXISTS idx_resurface_capture
                    ON resurface_events (capture_id);
                "#,
            )
            .context("creating database tables")?;
        Ok(())
    }

    // -----------------------------------------------------------------------
    // Capture CRUD
    // -----------------------------------------------------------------------

    /// Persist a newly captured article.  If a capture with the same
    /// `capture_id` already exists the insert is silently ignored
    /// (`INSERT OR IGNORE`).
    pub fn save_capture(&self, capture: &crate::ipc::CaptureResult) -> Result<()> {
        self.conn
            .execute(
                r#"
                INSERT OR IGNORE INTO captures
                    (capture_id, timestamp, title, source_url, content_markdown,
                     byline, excerpt, word_count, prediction_error_score)
                VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, 0.0)
                "#,
                params![
                    capture.capture_id,
                    capture.timestamp,
                    capture.title,
                    capture.source_url,
                    capture.content_markdown,
                    capture.byline,
                    capture.excerpt,
                    capture.word_count,
                ],
            )
            .with_context(|| {
                format!("saving capture id={}", capture.capture_id)
            })?;
        Ok(())
    }

    /// Update the `prediction_error_score` for a capture after the inference
    /// engine has processed it.
    pub fn update_prediction_error(&self, capture_id: &str, score: f64) -> Result<()> {
        self.conn
            .execute(
                "UPDATE captures SET prediction_error_score = ?1 WHERE capture_id = ?2",
                params![score, capture_id],
            )
            .with_context(|| {
                format!("updating prediction error for capture id={capture_id}")
            })?;
        Ok(())
    }

    /// Attach or update a user note on a capture.
    pub fn update_user_note(&self, capture_id: &str, user_note: &str) -> Result<()> {
        self.conn
            .execute(
                "UPDATE captures SET user_note = ?1 WHERE capture_id = ?2",
                params![user_note, capture_id],
            )
            .with_context(|| {
                format!("updating user note for capture id={capture_id}")
            })?;
        Ok(())
    }

    /// Fetch a single capture row by its ID.  Returns `None` when not found.
    pub fn get_capture(&self, capture_id: &str) -> Result<Option<CaptureRow>> {
        let mut stmt = self.conn.prepare(
            r#"
            SELECT capture_id, timestamp, title, source_url, content_markdown,
                   byline, excerpt, word_count, prediction_error_score,
                   user_note, topic_cluster_id, created_at
            FROM captures
            WHERE capture_id = ?1
            "#,
        )?;

        let mut rows = stmt.query_map(params![capture_id], |row| {
            Ok(CaptureRow {
                capture_id: row.get(0)?,
                timestamp: row.get(1)?,
                title: row.get(2)?,
                source_url: row.get(3)?,
                content_markdown: row.get(4)?,
                byline: row.get(5)?,
                excerpt: row.get(6)?,
                word_count: row.get::<_, i64>(7)? as u32,
                prediction_error_score: row.get(8)?,
                user_note: row.get(9)?,
                topic_cluster_id: row.get(10)?,
                created_at: row.get(11)?,
            })
        })?;

        match rows.next() {
            Some(row) => Ok(Some(row.context("reading capture row")?)),
            None => Ok(None),
        }
    }

    /// Return all captures ordered by most-recently created first.
    pub fn list_captures(&self, limit: usize) -> Result<Vec<CaptureRow>> {
        let mut stmt = self.conn.prepare(
            r#"
            SELECT capture_id, timestamp, title, source_url, content_markdown,
                   byline, excerpt, word_count, prediction_error_score,
                   user_note, topic_cluster_id, created_at
            FROM captures
            ORDER BY created_at DESC
            LIMIT ?1
            "#,
        )?;

        let rows = stmt
            .query_map(params![limit as i64], |row| {
                Ok(CaptureRow {
                    capture_id: row.get(0)?,
                    timestamp: row.get(1)?,
                    title: row.get(2)?,
                    source_url: row.get(3)?,
                    content_markdown: row.get(4)?,
                    byline: row.get(5)?,
                    excerpt: row.get(6)?,
                    word_count: row.get::<_, i64>(7)? as u32,
                    prediction_error_score: row.get(8)?,
                    user_note: row.get(9)?,
                    topic_cluster_id: row.get(10)?,
                    created_at: row.get(11)?,
                })
            })?
            .collect::<rusqlite::Result<Vec<_>>>()
            .context("listing captures")?;

        Ok(rows)
    }

    // -----------------------------------------------------------------------
    // Resurface events
    // -----------------------------------------------------------------------

    /// Append a resurface event row.
    ///
    /// # Arguments
    /// * `capture_id`         – The capture that was surfaced.
    /// * `action`             – What the user did: "clicked" | "dismissed" | "ignored".
    /// * `efe_score`          – Expected Free Energy score at the time of resurfacing.
    /// * `context_similarity` – Cosine similarity between current context and capture embedding.
    pub fn log_resurface_event(
        &self,
        capture_id: &str,
        action: &str,
        efe_score: f64,
        context_similarity: f64,
    ) -> Result<()> {
        let event_id = uuid::Uuid::new_v4().to_string();
        self.conn
            .execute(
                r#"
                INSERT INTO resurface_events
                    (event_id, capture_id, action, efe_score, context_similarity)
                VALUES (?1, ?2, ?3, ?4, ?5)
                "#,
                params![event_id, capture_id, action, efe_score, context_similarity],
            )
            .with_context(|| {
                format!(
                    "logging resurface event for capture id={capture_id} action={action}"
                )
            })?;
        Ok(())
    }

    /// Return recent resurface events for a capture, newest first.
    pub fn get_resurface_events(
        &self,
        capture_id: &str,
        limit: usize,
    ) -> Result<Vec<ResurfaceEventRow>> {
        let mut stmt = self.conn.prepare(
            r#"
            SELECT event_id, capture_id, action, efe_score, context_similarity, occurred_at
            FROM resurface_events
            WHERE capture_id = ?1
            ORDER BY occurred_at DESC
            LIMIT ?2
            "#,
        )?;

        let rows = stmt
            .query_map(params![capture_id, limit as i64], |row| {
                Ok(ResurfaceEventRow {
                    event_id: row.get(0)?,
                    capture_id: row.get(1)?,
                    action: row.get(2)?,
                    efe_score: row.get(3)?,
                    context_similarity: row.get(4)?,
                    occurred_at: row.get(5)?,
                })
            })?
            .collect::<rusqlite::Result<Vec<_>>>()
            .context("reading resurface events")?;

        Ok(rows)
    }
}
