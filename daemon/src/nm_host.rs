//! corteon-nm-host — Native Messaging host binary.
//!
//! Chrome launches this binary when the extension calls
//! `chrome.runtime.connectNative("com.corteon.daemon")`.
//!
//! Protocol
//! --------
//! * **Chrome ↔ NM host**: 4-byte LE length prefix + UTF-8 JSON body on
//!   stdin/stdout.
//! * **NM host ↔ daemon**: same framing over the Unix domain socket
//!   `/tmp/corteon.sock`.
//!
//! This binary is intentionally *thin*: it only relays bytes between the two
//! channels and reconnects to the daemon socket if it drops.

use anyhow::{Context, Result};
use std::time::Duration;
use tokio::{
    io::{self, AsyncReadExt, AsyncWriteExt},
    net::UnixStream,
    time::sleep,
};

const UNIX_SOCK: &str = "/tmp/corteon.sock";
/// Maximum allowed message body length (16 MiB).
const MAX_MSG_LEN: u32 = 16 * 1024 * 1024;

// ---------------------------------------------------------------------------
// Framing helpers
// ---------------------------------------------------------------------------

/// Read one length-prefixed message from `reader`.
/// Returns `None` on clean EOF.
async fn read_framed<R>(reader: &mut R) -> Result<Option<Vec<u8>>>
where
    R: AsyncReadExt + Unpin,
{
    let mut len_buf = [0u8; 4];
    match reader.read_exact(&mut len_buf).await {
        Ok(_) => {}
        Err(e) if e.kind() == io::ErrorKind::UnexpectedEof => return Ok(None),
        Err(e) => return Err(e.into()),
    }
    let len = u32::from_le_bytes(len_buf);
    if len == 0 || len > MAX_MSG_LEN {
        anyhow::bail!("implausible message length: {len}");
    }
    let mut body = vec![0u8; len as usize];
    reader.read_exact(&mut body).await?;
    Ok(Some(body))
}

/// Write one length-prefixed message to `writer`.
async fn write_framed<W>(writer: &mut W, body: &[u8]) -> Result<()>
where
    W: AsyncWriteExt + Unpin,
{
    let len = body.len() as u32;
    writer.write_all(&len.to_le_bytes()).await?;
    writer.write_all(body).await?;
    writer.flush().await?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Socket relay (one connected session)
// ---------------------------------------------------------------------------

/// Relay messages bidirectionally between `socket` and `stdin`/`stdout`
/// until either side closes the connection.
///
/// Returns `Ok(true)` when we should attempt to reconnect to the daemon,
/// `Ok(false)` when stdin has been closed (Chrome exited).
async fn relay_session(socket: UnixStream) -> Result<bool> {
    let (mut sock_read, mut sock_write) = socket.into_split();

    // We read stdin and write stdout on the main task, and handle the
    // socket direction on a spawned task so both can proceed concurrently.

    // Channel: socket → stdout
    let (sock_to_stdout_tx, mut sock_to_stdout_rx) =
        tokio::sync::mpsc::channel::<Vec<u8>>(64);
    // Channel: signal that socket read side finished
    let (socket_done_tx, mut socket_done_rx) =
        tokio::sync::oneshot::channel::<bool>(); // true = daemon closed

    // Spawn: daemon socket reader → sends to channel
    tokio::spawn(async move {
        loop {
            match read_framed(&mut sock_read).await {
                Ok(Some(body)) => {
                    if sock_to_stdout_tx.send(body).await.is_err() {
                        break;
                    }
                }
                Ok(None) => {
                    // Daemon closed the socket — signal reconnect.
                    let _ = socket_done_tx.send(true);
                    return;
                }
                Err(_e) => {
                    let _ = socket_done_tx.send(true);
                    return;
                }
            }
        }
        let _ = socket_done_tx.send(true);
    });

    let mut stdin = io::stdin();
    let mut stdout = io::stdout();

    loop {
        tokio::select! {
            // stdin → daemon socket
            result = read_framed(&mut stdin) => {
                match result {
                    Ok(Some(body)) => {
                        write_framed(&mut sock_write, &body).await
                            .context("writing to daemon socket")?;
                    }
                    Ok(None) => {
                        // Chrome closed stdin — we are done, do not reconnect.
                        return Ok(false);
                    }
                    Err(e) => {
                        // Treat read errors from Chrome as EOF.
                        eprintln!("corteon-nm-host: stdin read error: {e}");
                        return Ok(false);
                    }
                }
            }

            // daemon socket → stdout
            Some(body) = sock_to_stdout_rx.recv() => {
                write_framed(&mut stdout, &body).await
                    .context("writing to Chrome stdout")?;
            }

            // daemon socket was closed
            _ = &mut socket_done_rx => {
                return Ok(true); // reconnect
            }
        }
    }
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() -> Result<()> {
    // NM hosts must not write anything to stdout before the Chrome handshake,
    // so we direct our own diagnostics to stderr only.
    eprintln!("corteon-nm-host: starting");

    loop {
        eprintln!("corteon-nm-host: connecting to daemon at {UNIX_SOCK}");

        match UnixStream::connect(UNIX_SOCK).await {
            Ok(socket) => {
                eprintln!("corteon-nm-host: connected");
                match relay_session(socket).await {
                    Ok(true) => {
                        // Daemon closed its end — wait and retry.
                        eprintln!(
                            "corteon-nm-host: daemon disconnected, retrying in 2 s"
                        );
                        sleep(Duration::from_secs(2)).await;
                    }
                    Ok(false) => {
                        // Chrome exited — clean shutdown.
                        eprintln!("corteon-nm-host: Chrome closed stdin, exiting");
                        return Ok(());
                    }
                    Err(e) => {
                        eprintln!("corteon-nm-host: relay error: {e:#}, retrying in 2 s");
                        sleep(Duration::from_secs(2)).await;
                    }
                }
            }
            Err(e) => {
                eprintln!(
                    "corteon-nm-host: cannot connect to {UNIX_SOCK}: {e}, retrying in 2 s"
                );
                sleep(Duration::from_secs(2)).await;
            }
        }
    }
}
