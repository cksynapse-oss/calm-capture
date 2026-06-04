mod ipc;
mod storage;

use std::{
    collections::HashMap,
    net::SocketAddr,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

use anyhow::{Context, Result};
use futures_util::{SinkExt, StreamExt};
use global_hotkey::{hotkey::HotKey, GlobalHotKeyEvent, GlobalHotKeyManager};
use ipc::{
    CapturePayload, DaemonToExtension, DaemonToUI, ExtensionMessage, InferenceMessage, Resurface,
    Toast, UIToDaemon,
};
use storage::Storage;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, UnixListener, UnixStream},
    sync::{broadcast, Mutex},
};
use tokio_tungstenite::{accept_async, tungstenite::Message};
use tracing::{error, info, warn};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const WS_ADDR: &str = "127.0.0.1:9741";
const UNIX_SOCK: &str = "/tmp/corteon.sock";

// ---------------------------------------------------------------------------
// Client registry
// ---------------------------------------------------------------------------

/// Shared map of WebSocket path → list of client broadcast senders.
type ClientMap = Arc<Mutex<HashMap<String, Vec<broadcast::Sender<String>>>>>;

// ---------------------------------------------------------------------------
// Unix socket helpers  (daemon-side)
// ---------------------------------------------------------------------------

/// Write a length-prefixed JSON message to a `UnixStream`.
async fn write_framed(stream: &mut UnixStream, json: &str) -> Result<()> {
    let bytes = json.as_bytes();
    let len = bytes.len() as u32;
    stream.write_all(&len.to_le_bytes()).await?;
    stream.write_all(bytes).await?;
    Ok(())
}

/// Read a length-prefixed JSON message from a `UnixStream`.
/// Returns `None` on clean EOF.
async fn read_framed(stream: &mut UnixStream) -> Result<Option<String>> {
    let mut len_buf = [0u8; 4];
    match stream.read_exact(&mut len_buf).await {
        Ok(_) => {}
        Err(e) if e.kind() == std::io::ErrorKind::UnexpectedEof => return Ok(None),
        Err(e) => return Err(e.into()),
    }
    let len = u32::from_le_bytes(len_buf) as usize;
    if len == 0 || len > 16 * 1024 * 1024 {
        anyhow::bail!("implausible frame length {len}");
    }
    let mut buf = vec![0u8; len];
    stream.read_exact(&mut buf).await?;
    Ok(Some(String::from_utf8(buf)?))
}

// ---------------------------------------------------------------------------
// Broadcast helpers
// ---------------------------------------------------------------------------

/// Fan-out `msg` to every client registered at `path`.
/// Dead senders are pruned automatically.
async fn broadcast_to(clients: &ClientMap, path: &str, msg: &str) {
    let mut map = clients.lock().await;
    if let Some(senders) = map.get_mut(path) {
        senders.retain(|tx| tx.send(msg.to_owned()).is_ok());
    }
}

/// Send a message to all inference clients at /inference.
async fn send_to_inference(clients: &ClientMap, msg: &str) {
    broadcast_to(clients, "/inference", msg).await;
}

/// Send a message to all UI clients at /ui.
async fn send_to_ui(clients: &ClientMap, msg: &str) {
    broadcast_to(clients, "/ui", msg).await;
}

// ---------------------------------------------------------------------------
// WebSocket connection handler
// ---------------------------------------------------------------------------

async fn handle_ws_connection(
    raw_stream: tokio::net::TcpStream,
    peer: SocketAddr,
    clients: ClientMap,
    inference_in_tx: tokio::sync::mpsc::Sender<InferenceMessage>,
    ui_in_tx: tokio::sync::mpsc::Sender<UIToDaemon>,
) {
    let ws_stream = match accept_async(raw_stream).await {
        Ok(ws) => ws,
        Err(e) => {
            warn!("WebSocket handshake failed from {peer}: {e}");
            return;
        }
    };

    // Path-based client registration protocol:
    // The connecting client sends `{"path":"/ui"}` or `{"path":"/inference"}`
    // as its very first text frame.

    let (mut ws_sink, mut ws_stream_rx) = ws_stream.split();

    let path = match ws_stream_rx.next().await {
        Some(Ok(Message::Text(txt))) => {
            #[derive(serde::Deserialize)]
            struct Reg {
                path: String,
            }
            match serde_json::from_str::<Reg>(&txt) {
                Ok(r) => r.path,
                Err(_) => {
                    warn!("bad registration frame from {peer}: {txt}");
                    return;
                }
            }
        }
        other => {
            warn!("unexpected first frame from {peer}: {other:?}");
            return;
        }
    };

    info!("WebSocket client registered at path={path} peer={peer}");

    // Per-client broadcast channel.
    let (out_tx, mut out_rx) = broadcast::channel::<String>(64);
    {
        let mut map = clients.lock().await;
        map.entry(path.clone()).or_default().push(out_tx);
    }

    // Writer task: pull messages off the broadcast channel and push to WS.
    let write_task = tokio::spawn(async move {
        while let Ok(msg) = out_rx.recv().await {
            if ws_sink.send(Message::Text(msg)).await.is_err() {
                break;
            }
        }
    });

    // Reader: process inbound messages from this client.
    while let Some(msg_result) = ws_stream_rx.next().await {
        match msg_result {
            Ok(Message::Text(txt)) => match path.as_str() {
                "/ui" => match ipc::from_json::<UIToDaemon>(&txt) {
                    Ok(msg) => {
                        let _ = ui_in_tx.send(msg).await;
                    }
                    Err(e) => warn!("bad UI message: {e}"),
                },
                "/inference" => match ipc::from_json::<InferenceMessage>(&txt) {
                    Ok(msg) => {
                        let _ = inference_in_tx.send(msg).await;
                    }
                    Err(e) => warn!("bad inference message: {e}"),
                },
                other => warn!("unknown path {other}"),
            },
            Ok(Message::Close(_)) | Err(_) => break,
            _ => {}
        }
    }

    // Clean-up: drop dead senders.
    {
        let mut map = clients.lock().await;
        if let Some(senders) = map.get_mut(&path) {
            senders.retain(|tx| tx.receiver_count() > 0);
        }
    }

    write_task.abort();
    info!("WebSocket client disconnected path={path} peer={peer}");
}

// ---------------------------------------------------------------------------
// NM Host Unix socket listener
// ---------------------------------------------------------------------------

/// Accept connections from the NM host process and handle one at a time.
async fn nm_socket_listener(
    ext_tx: tokio::sync::mpsc::Sender<ExtensionMessage>,
    mut daemon_to_ext_rx: tokio::sync::mpsc::Receiver<DaemonToExtension>,
    nm_host_connected: Arc<AtomicBool>,
) -> Result<()> {
    let _ = std::fs::remove_file(UNIX_SOCK);
    let listener = UnixListener::bind(UNIX_SOCK)
        .with_context(|| format!("binding Unix socket {UNIX_SOCK}"))?;

    info!("NM host socket listening at {UNIX_SOCK}");

    loop {
        match listener.accept().await {
            Ok((mut stream, _addr)) => {
                info!("NM host connected");
                nm_host_connected.store(true, Ordering::SeqCst);
                loop {
                    tokio::select! {
                        frame = read_framed(&mut stream) => {
                            match frame {
                                Ok(Some(json)) => {
                                    info!("Daemon Unix socket received frame (len {}): {}", json.len(), &json[..json.len().min(1000)]);
                                    match ipc::from_json::<ExtensionMessage>(&json) {
                                        Ok(msg) => {
                                            info!("Deserialized ExtensionMessage successfully: {:?}", msg);
                                            let _ = ext_tx.send(msg).await;
                                        }
                                        Err(e) => warn!("bad extension message: {e} | raw: {}", json),
                                    }
                                }
                                Ok(None) => {
                                    info!("NM host disconnected");
                                    nm_host_connected.store(false, Ordering::SeqCst);
                                    break;
                                }
                                Err(e) => {
                                    error!("NM socket read error: {e}");
                                    nm_host_connected.store(false, Ordering::SeqCst);
                                    break;
                                }
                            }
                        }
                        msg = daemon_to_ext_rx.recv() => {
                            match msg {
                                Some(m) => {
                                    let json = ipc::to_json(&m);
                                    if let Err(e) = write_framed(&mut stream, &json).await {
                                        error!("NM socket write error: {e}");
                                        nm_host_connected.store(false, Ordering::SeqCst);
                                        break;
                                    }
                                }
                                None => break,
                            }
                        }
                    }
                }
            }
            Err(e) => {
                error!("Unix accept error: {e}");
                tokio::time::sleep(std::time::Duration::from_secs(1)).await;
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Async daemon core (runs on a background OS thread)
// ---------------------------------------------------------------------------

async fn run_daemon(
    hotkey_rx: crossbeam_channel::Receiver<GlobalHotKeyEvent>,
) -> Result<()> {
    // --- Data directory ---
    let data_dir: PathBuf = {
        let home = std::env::var("HOME").context("HOME env var not set")?;
        PathBuf::from(home).join(".corteon")
    };
    std::fs::create_dir_all(&data_dir)
        .with_context(|| format!("creating data dir {}", data_dir.display()))?;

    let db_path = data_dir.join("corteon.db");
    info!("Database path: {}", db_path.display());

    // --- Storage ---
    let storage = Arc::new(Mutex::new(
        Storage::new(&db_path).context("opening storage")?,
    ));

    // --- Client registry ---
    let clients: ClientMap = Arc::new(Mutex::new(HashMap::new()));

    // --- Channels ---
    let (ext_tx, mut ext_rx) = tokio::sync::mpsc::channel::<ExtensionMessage>(64);
    let (daemon_to_ext_tx, daemon_to_ext_rx) =
        tokio::sync::mpsc::channel::<DaemonToExtension>(64);
    let (inference_in_tx, mut inference_in_rx) =
        tokio::sync::mpsc::channel::<InferenceMessage>(64);
    let (ui_in_tx, mut ui_in_rx) = tokio::sync::mpsc::channel::<UIToDaemon>(64);

    // --- NM host connection tracking ---
    let nm_host_connected = Arc::new(AtomicBool::new(false));

    // --- Unix socket (NM host) ---
    {
        let ext_tx_clone = ext_tx.clone();
        let nm_flag = nm_host_connected.clone();
        tokio::spawn(nm_socket_listener(ext_tx_clone, daemon_to_ext_rx, nm_flag));
    }

    // --- WebSocket server ---
    let ws_listener = TcpListener::bind(WS_ADDR)
        .await
        .with_context(|| format!("binding WebSocket server on {WS_ADDR}"))?;
    info!("WebSocket server listening on ws://{WS_ADDR}");

    {
        let clients_clone = clients.clone();
        let inference_in_tx_clone = inference_in_tx.clone();
        let ui_in_tx_clone = ui_in_tx.clone();

        tokio::spawn(async move {
            loop {
                match ws_listener.accept().await {
                    Ok((stream, peer)) => {
                        let clients = clients_clone.clone();
                        let inference_in_tx = inference_in_tx_clone.clone();
                        let ui_in_tx = ui_in_tx_clone.clone();

                        tokio::spawn(handle_ws_connection(
                            stream,
                            peer,
                            clients,
                            inference_in_tx,
                            ui_in_tx,
                        ));
                    }
                    Err(e) => error!("TCP accept error: {e}"),
                }
            }
        });
    }

    // --- Main event loop ---
    info!("Entering main event loop");
    loop {
        // Non-blocking poll of the crossbeam hotkey receiver.
        if hotkey_rx.try_recv().is_ok() {
            if nm_host_connected.load(Ordering::SeqCst) {
                info!("Hotkey triggered — sending TriggerCapture to extension");
                let _ = daemon_to_ext_tx.send(DaemonToExtension::TriggerCapture {}).await;
            } else {
                // Zero-permission fallback: read clipboard text
                info!("Hotkey triggered — no NM host; attempting clipboard capture");
                let clipboard_text = tokio::task::spawn_blocking(|| {
                    match arboard::Clipboard::new() {
                        Ok(mut cb) => match cb.get_text() {
                            Ok(text) if !text.trim().is_empty() => Some(text),
                            _ => None,
                        },
                        Err(e) => {
                            tracing::warn!("Clipboard access failed: {e}");
                            None
                        }
                    }
                })
                .await
                .unwrap_or(None);

                if let Some(text) = clipboard_text {
                    let word_count = text.split_whitespace().count() as u32;
                    let capture_id = uuid::Uuid::new_v4().to_string();
                    let excerpt: String = text.chars().take(200).collect();
                    let title_preview: String = text.lines().next().unwrap_or("Clipboard Capture").chars().take(80).collect();
                    let timestamp = chrono::Utc::now().to_rfc3339();

                    info!("Clipboard capture: {word_count} words, title='{title_preview}'");

                    let payload = CapturePayload {
                        capture_id: capture_id.clone(),
                        title: title_preview.clone(),
                        source_url: "clipboard://desktop".to_owned(),
                        content_markdown: text,
                        byline: None,
                        excerpt: excerpt.clone(),
                        word_count,
                        timestamp,
                        content_type: "desktop_clipboard".to_owned(),
                    };
                    let inf_msg = InferenceMessage::NewCapture(payload);
                    send_to_inference(&clients, &ipc::to_json(&inf_msg)).await;

                    // Notify UI with capture confirmation
                    let cc = DaemonToUI::CaptureComplete(ipc::CaptureComplete {
                        capture_id,
                        title: title_preview,
                        excerpt,
                        word_count,
                        prediction_error_score: 0.0,
                    });
                    send_to_ui(&clients, &ipc::to_json(&cc)).await;

                    // Toast confirmation
                    let toast = DaemonToUI::Toast(Toast {
                        message: format!("📋 Clipboard captured ({word_count} words)"),
                        level: "info".to_owned(),
                    });
                    send_to_ui(&clients, &ipc::to_json(&toast)).await;
                } else {
                    info!("Clipboard empty — falling back to ScreenCaptureRequest");
                    let scr_msg = DaemonToUI::ScreenCaptureRequest {};
                    send_to_ui(&clients, &ipc::to_json(&scr_msg)).await;
                }
            }
        }

        tokio::select! {
            // ---- Messages from the Chrome extension (via NM host) ----
            Some(ext_msg) = ext_rx.recv() => {
                match ext_msg {
                    ExtensionMessage::CaptureResult(capture) => {
                        info!("CaptureResult received id={} title='{}' excerpt='{}' byline={:?} word_count={} content_markdown_len={}",
                              capture.capture_id, capture.title, capture.excerpt, capture.byline, capture.word_count, capture.content_markdown.len());

                        // 1. Notify UI immediately (capture confirmation overlay)
                        let cc = DaemonToUI::CaptureComplete(ipc::CaptureComplete {
                            capture_id: capture.capture_id.clone(),
                            title: capture.title.clone(),
                            excerpt: capture.excerpt.clone(),
                            word_count: capture.word_count,
                            prediction_error_score: 0.0,
                        });
                        send_to_ui(&clients, &ipc::to_json(&cc)).await;

                        // 2. Send to inference engine (inference handles persistence
                        //    with its own schema — avoids schema mismatch)
                        let inf_msg = InferenceMessage::NewCapture(
                            ipc::CapturePayload::from(&capture),
                        );
                        send_to_inference(&clients, &ipc::to_json(&inf_msg)).await;
                    }

                    ExtensionMessage::TabContext(tab) => {
                        info!("TabContext url={}", tab.url);
                        let inf_msg = InferenceMessage::TabContext(tab);
                        send_to_inference(&clients, &ipc::to_json(&inf_msg)).await;
                    }

                    ExtensionMessage::Heartbeat(_) | ExtensionMessage::Pong(_) => {
                        // ignore heartbeat and pongs
                    }

                    ExtensionMessage::CaptureError(err) => {
                        error!("CaptureError on {}: {}", err.url, err.error);
                    }
                }
            }

            // ---- Messages from the inference engine (via /inference WS) ----
            Some(inf_msg) = inference_in_rx.recv() => {
                match inf_msg {
                    InferenceMessage::ResurfaceSignal(sig) => {
                        info!(
                            "ResurfaceSignal received id={} efe={:.3}",
                            sig.capture_id, sig.efe_score
                        );
                        let resurface = DaemonToUI::Resurface(Resurface {
                            capture_id: sig.capture_id.clone(),
                            title: sig.title.clone(),
                            excerpt: sig.excerpt.clone(),
                            user_note: sig.user_note.clone(),
                            relevance_score: sig.relevance_score,
                            efe_score: sig.efe_score,
                            display_intensity: sig.display_intensity,
                            reason: sig.reason.clone(),
                        });
                        send_to_ui(&clients, &ipc::to_json(&resurface)).await;
                    }
                    other => {
                        warn!("Unexpected message from inference engine: {other:?}");
                    }
                }
            }

            // ---- Messages from the UI (via /ui WS) ----
            Some(ui_msg) = ui_in_rx.recv() => {
                match ui_msg {
                    UIToDaemon::UserFeedback(ref fb) => {
                        info!(
                            "UserFeedback id={} action={}",
                            fb.capture_id, fb.action
                        );
                        {
                            let store = storage.lock().await;
                            if let Err(e) = store.log_resurface_event(
                                &fb.capture_id,
                                &fb.action,
                                0.0,
                                0.0,
                            ) {
                                error!("log_resurface_event error: {e}");
                            }
                        }
                        let inf_msg = InferenceMessage::UserFeedback(fb.clone());
                        send_to_inference(&clients, &ipc::to_json(&inf_msg)).await;
                    }

                    UIToDaemon::CaptureNote(ref note) => {
                        info!("CaptureNote id={}", note.capture_id);
                        let store = storage.lock().await;
                        if let Err(e) = store.update_user_note(&note.capture_id, &note.user_note) {
                            error!("update_user_note error: {e}");
                        }
                    }

                    UIToDaemon::ScreenCaptureResult(ref scr) => {
                        info!(
                            "ScreenCaptureResult received app={} title={}",
                            scr.app_name, scr.window_title
                        );
                        let capture_id = uuid::Uuid::new_v4().to_string();
                        let word_count = scr.ocr_text.split_whitespace().count() as u32;

                        // Forward to inference engine as a NewCapture with content_type "screen_ocr"
                        let payload = CapturePayload {
                            capture_id: capture_id.clone(),
                            title: scr.window_title.clone(),
                            source_url: format!("app://{}", scr.app_name),
                            content_markdown: scr.ocr_text.clone(),
                            byline: Some(scr.app_name.clone()),
                            excerpt: scr.ocr_text.chars().take(200).collect(),
                            word_count,
                            timestamp: scr.timestamp.clone(),
                            content_type: "screen_ocr".to_owned(),
                        };
                        let inf_msg = InferenceMessage::NewCapture(payload);
                        send_to_inference(&clients, &ipc::to_json(&inf_msg)).await;

                        // Notify UI with a capture confirmation
                        let cc = DaemonToUI::CaptureComplete(ipc::CaptureComplete {
                            capture_id,
                            title: scr.window_title.clone(),
                            excerpt: scr.ocr_text.chars().take(120).collect(),
                            word_count,
                            prediction_error_score: 0.0,
                        });
                        send_to_ui(&clients, &ipc::to_json(&cc)).await;
                    }
                }
            }

            // Yield regularly so hotkey polling does not starve async tasks.
            _ = tokio::time::sleep(std::time::Duration::from_millis(50)) => {}
        }
    }
}

// ---------------------------------------------------------------------------
// main — keeps the primary thread for the macOS run loop
// ---------------------------------------------------------------------------

fn main() -> Result<()> {
    // --- Tracing ---
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    info!("Corteon daemon starting");

    // --- Hotkey (must be set up on the main thread on macOS) ---
    let hotkey_rx: crossbeam_channel::Receiver<GlobalHotKeyEvent> =
        match (|| -> Result<(GlobalHotKeyManager, _)> {
            let manager = GlobalHotKeyManager::new().context("creating GlobalHotKeyManager")?;
            let hotkey = HotKey::new(
                Some(
                    global_hotkey::hotkey::Modifiers::META
                        | global_hotkey::hotkey::Modifiers::SHIFT,
                ),
                global_hotkey::hotkey::Code::KeyK,
            );
            manager
                .register(hotkey)
                .context("registering hotkey Cmd+Shift+K")?;
            let rx = GlobalHotKeyEvent::receiver().clone();
            Ok((manager, rx))
        })() {
            Ok((_mgr, rx)) => {
                // Keep _mgr alive for the whole process by leaking it.
                // The GlobalHotKeyManager must stay alive as long as we want
                // hotkeys to fire; leaking is safe here since this is a daemon.
                Box::leak(Box::new(_mgr));
                rx
            }
            Err(e) => {
                warn!("Hotkey registration failed (continuing without it): {e}");
                // Return a receiver from a channel that will never send.
                crossbeam_channel::never()
            }
        };

    // --- Spawn the async daemon on a dedicated OS thread ---
    // The main thread is reserved for the macOS NSApplication event loop
    // that global-hotkey needs to dispatch events.
    let daemon_handle = std::thread::Builder::new()
        .name("corteon-async".into())
        .spawn(move || {
            tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .build()
                .expect("tokio runtime")
                .block_on(run_daemon(hotkey_rx))
        })
        .context("spawning daemon thread")?;

    // --- macOS main-thread event loop ---
    // winit's EventLoop must run on the main thread to keep the NSApplication
    // alive so that global-hotkey events are dispatched correctly.
    //
    // winit 0.30 uses the ApplicationHandler trait + run_app instead of the
    // old closure-based run().
    #[cfg(target_os = "macos")]
    {
        use winit::application::ApplicationHandler;
        use winit::event::WindowEvent;
        use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
        use winit::window::WindowId;

        struct HeadlessApp {
            daemon_finished: bool,
        }

        impl ApplicationHandler for HeadlessApp {
            fn resumed(&mut self, _event_loop: &ActiveEventLoop) {
                // No windows to create; we only need the run loop alive.
            }

            fn window_event(
                &mut self,
                event_loop: &ActiveEventLoop,
                _window_id: WindowId,
                _event: WindowEvent,
            ) {
                if self.daemon_finished {
                    event_loop.exit();
                }
            }

            fn about_to_wait(&mut self, event_loop: &ActiveEventLoop) {
                if self.daemon_finished {
                    event_loop.exit();
                }
            }

            fn exiting(&mut self, _event_loop: &ActiveEventLoop) {
                info!("Event loop exiting");
            }
        }

        let event_loop = EventLoop::new().expect("winit EventLoop");
        event_loop.set_control_flow(ControlFlow::Wait);

        let mut app = HeadlessApp {
            daemon_finished: false,
        };

        // Periodically check whether the daemon thread has exited.
        // We use a dedicated thread that sets a flag and sends a user event.
        // Because HeadlessApp has no windows, we drive exit via about_to_wait.
        std::thread::spawn(move || loop {
            std::thread::sleep(std::time::Duration::from_millis(200));
            if daemon_handle.is_finished() {
                // Wake the event loop; about_to_wait will call exit().
                // (No user-event proxy available without creating a window,
                //  so we use a process-wide atomic flag.)
                std::process::exit(1);
            }
        });

        event_loop.run_app(&mut app).expect("winit run_app");
    }

    // On non-macOS platforms (Linux, Windows) just block on the daemon thread.
    #[cfg(not(target_os = "macos"))]
    {
        match daemon_handle.join() {
            Ok(Ok(())) => {}
            Ok(Err(e)) => return Err(e),
            Err(_) => anyhow::bail!("daemon thread panicked"),
        }
    }

    Ok(())
}
