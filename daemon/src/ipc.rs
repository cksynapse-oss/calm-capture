use serde::{Deserialize, Serialize};

// ---------------------------------------------------------------------------
// Primitive payload structs
// ---------------------------------------------------------------------------

/// A capture result as received from the Chrome extension via Native Messaging.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaptureResult {
    pub capture_id: String,
    pub timestamp: String,
    pub title: String,
    pub source_url: String,
    pub content_markdown: String,
    pub byline: Option<String>,
    pub excerpt: String,
    pub word_count: u32,
}

/// Payload carried by the `CaptureComplete` daemon→UI message.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaptureComplete {
    pub capture_id: String,
    pub title: String,
    pub excerpt: String,
    pub word_count: u32,
    pub prediction_error_score: f64,
}

/// Payload carried by the `Resurface` daemon→UI message.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Resurface {
    pub capture_id: String,
    pub title: String,
    pub excerpt: String,
    pub user_note: Option<String>,
    pub relevance_score: f64,
    pub efe_score: f64,
    pub display_intensity: f64,
    pub reason: String,
}

/// Payload carried by the `Toast` daemon→UI message.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Toast {
    pub message: String,
    /// "info" | "error" | "warning"
    pub level: String,
}

/// Payload carried by the `UserFeedback` UI→daemon message.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserFeedback {
    pub capture_id: String,
    /// "clicked" | "dismissed" | "ignored"
    pub action: String,
    pub duration_visible_ms: u64,
}

/// Payload carried by the `CaptureNote` UI→daemon message.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaptureNote {
    pub capture_id: String,
    pub user_note: String,
}

/// Payload carried by the `ScreenCaptureResult` UI→daemon message.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScreenCaptureResultPayload {
    pub ocr_text: String,
    pub app_name: String,
    pub window_title: String,
    pub timestamp: String,
}

/// Payload for a new-capture message sent to the inference engine.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CapturePayload {
    pub capture_id: String,
    pub title: String,
    pub source_url: String,
    pub content_markdown: String,
    pub byline: Option<String>,
    pub excerpt: String,
    pub word_count: u32,
    pub timestamp: String,
    /// "browser" (default) or "screen_ocr"
    #[serde(default = "default_content_type")]
    pub content_type: String,
}

fn default_content_type() -> String {
    "browser".to_owned()
}

impl From<&CaptureResult> for CapturePayload {
    fn from(cr: &CaptureResult) -> Self {
        CapturePayload {
            capture_id: cr.capture_id.clone(),
            title: cr.title.clone(),
            source_url: cr.source_url.clone(),
            content_markdown: cr.content_markdown.clone(),
            byline: cr.byline.clone(),
            excerpt: cr.excerpt.clone(),
            word_count: cr.word_count,
            timestamp: cr.timestamp.clone(),
            content_type: "browser".to_owned(),
        }
    }
}

/// Payload for a tab-context update forwarded from the extension.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TabContext {
    pub url: String,
    pub title: String,
}

/// Payload for the resurface signal emitted by the inference engine.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResurfaceSignal {
    pub capture_id: String,
    pub title: String,
    pub excerpt: String,
    pub user_note: Option<String>,
    pub relevance_score: f64,
    pub efe_score: f64,
    pub display_intensity: f64,
    pub reason: String,
}

// ---------------------------------------------------------------------------
// Daemon → UI messages  (WebSocket path /ui)
// ---------------------------------------------------------------------------

/// Messages the daemon pushes to the UI WebSocket client.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "payload")]
pub enum DaemonToUI {
    CaptureComplete(CaptureComplete),
    Resurface(Resurface),
    Toast(Toast),
    /// Ask the overlay to perform a native screen capture and OCR
    ScreenCaptureRequest {},
}

// ---------------------------------------------------------------------------
// UI → Daemon messages  (WebSocket path /ui)
// ---------------------------------------------------------------------------

/// Messages the UI client sends to the daemon.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "payload")]
pub enum UIToDaemon {
    UserFeedback(UserFeedback),
    CaptureNote(CaptureNote),
    /// The overlay finished a screen capture + OCR and sends the result back.
    ScreenCaptureResult(ScreenCaptureResultPayload),
}

// ---------------------------------------------------------------------------
// Daemon ↔ Inference Engine messages  (WebSocket path /inference)
// ---------------------------------------------------------------------------

/// Messages exchanged on the /inference WebSocket path.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "payload")]
pub enum InferenceMessage {
    /// Daemon → Inference: a new article was captured.
    NewCapture(CapturePayload),
    /// Daemon → Inference: the user switched browser tabs.
    TabContext(TabContext),
    /// Daemon → Inference: relay user feedback so the engine can update its model.
    UserFeedback(UserFeedback),
    /// Inference → Daemon: ask the daemon to resurface a specific capture to the UI.
    ResurfaceSignal(ResurfaceSignal),
}

// ---------------------------------------------------------------------------
// Extension → Daemon messages  (NM host / Unix socket relay)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Heartbeat {
    pub ts: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Pong {
    pub ts: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaptureError {
    pub error: String,
    pub url: String,
}

/// Messages that arrive from the Chrome extension via the NM host.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "payload")]
pub enum ExtensionMessage {
    /// Extension sends a fully-parsed capture result.
    CaptureResult(CaptureResult),
    /// Extension reports the active tab URL/title whenever the user navigates.
    TabContext(TabContext),
    /// Extension heartbeat.
    Heartbeat(Heartbeat),
    /// Extension pong.
    Pong(Pong),
    /// Capture error.
    CaptureError(CaptureError),
}

/// Messages the daemon sends *to* the Chrome extension via the NM host.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "payload")]
pub enum DaemonToExtension {
    /// Ask the extension to capture the current page.
    TriggerCapture {},
    /// Generic toast for the extension popup.
    Toast(Toast),
}

// ---------------------------------------------------------------------------
// Top-level wrapper — useful when a single channel carries mixed traffic.
// ---------------------------------------------------------------------------

/// Top-level envelope that names the direction / sub-protocol of a message.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "payload")]
pub enum DaemonMessage {
    DaemonToUI(DaemonToUI),
    UIToDaemon(UIToDaemon),
    InferenceMessage(InferenceMessage),
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Serialize any serde-serializable value to a JSON `String`, panicking on
/// programmer error (should never happen for well-formed types).
pub fn to_json<T: Serialize>(value: &T) -> String {
    serde_json::to_string(value).expect("serialization of IPC message must not fail")
}

/// Deserialize from a JSON `&str`, returning an `anyhow::Error` on failure.
pub fn from_json<'a, T: Deserialize<'a>>(s: &'a str) -> anyhow::Result<T> {
    let result = serde_json::from_str(s);
    if let Err(ref e) = result {
        eprintln!("ipc::from_json failed: {} | raw: {}", e, s);
    }
    result.map_err(|e| anyhow::anyhow!("IPC deserialize error: {e}"))
}
