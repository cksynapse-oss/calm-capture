# Calm Capture

> An **Active Inference** knowledge resurfacing agent for macOS — captures web content while you browse and resurfaces relevant memories at the right moment using predictive coding principles.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         macOS Desktop                               │
│                                                                     │
│  ┌──────────────────┐   NM stdio   ┌──────────────────────────────┐│
│  │  Chrome Extension│◄────────────►│  corteon-nm-host (Rust)      ││
│  │  (content script │              └──────────┬───────────────────┘│
│  │   + hotkey)      │                         │ Unix socket        │
│  └──────────────────┘              ┌──────────▼───────────────────┐│
│                                    │  corteon-daemon (Rust)        ││
│                                    │  • Receive captured pages     ││
│                                    │  • SQLite knowledge store     ││
│                                    │  • WebSocket server :9741     ││
│                                    └──────────┬───────────────────┘│
│                                               │ ws://localhost:9741 │
│            ┌──────────────────────────────────▼──────────────────┐ │
│            │  inference_engine.py (Python)                        │ │
│            │  • spaCy NLP, TF-IDF, prediction-error scoring       │ │
│            │  • Resurface decision logic                          │ │
│            └──────────────────────────────────┬──────────────────┘ │
│                                               │ ws://localhost:9741 │
│            ┌──────────────────────────────────▼──────────────────┐ │
│            │  CorteonOverlay (Swift/AppKit + SwiftUI)             │ │
│            │  • Borderless floating panels                        │ │
│            │  • GhostNotificationView (resurface)                 │ │
│            │  • CapturePopoverView (confirmation)                 │ │
│            │  • MarginOverlayView (persistent luminous margin)    │ │
│            └──────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Rust + Cargo | 1.75+ | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| Python | 3.11+ | `brew install python@3.11` |
| Xcode CLI Tools | 15+ | `xcode-select --install` |
| Chrome | any | [google.com/chrome](https://google.com/chrome) |

---

## Step-by-Step Setup

### Step 1 — Build the Rust daemon

```bash
cd daemon
cargo build --release
# Produces:
#   daemon/target/release/corteon-daemon
#   daemon/target/release/corteon-nm-host
```

### Step 2 — Install Python dependencies

```bash
cd inference
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

Or use the convenience script (handles venv creation automatically):

```bash
bash start_inference.sh --install-only
```

### Step 3 — Build the Swift overlay

```bash
cd overlay
swift build -c release
# Produces: overlay/.build/release/CorteonOverlay
```

### Step 4 — Run the installer

```bash
bash install.sh
```

This script:
- Creates `~/.corteon/`
- Installs `com.corteon.daemon.plist` → `~/Library/LaunchAgents/`
- Installs Native Messaging manifests for Chrome **and** Firefox
- Calls `launchctl load` to start the daemon automatically

### Step 5 — Load the Chrome extension

1. Open **chrome://extensions**
2. Enable **Developer Mode** (top-right toggle)
3. Click **Load unpacked**
4. Select the `extension/` folder inside this project

> After loading, copy the Extension ID (e.g. `abcdefghijklmnopqrstuvwxyz123456`) and paste it into `com.corteon.capture.json` under `allowed_origins`, then re-run `install.sh` to refresh the NM manifest.

### Step 6 — Start the inference engine

```bash
bash start_inference.sh
```

The script will activate the venv (creating it on first run), verify the spaCy model, and exec the engine. Leave this terminal running or daemonise it as you prefer.

### Step 7 — Test the full pipeline

1. Open any article in Chrome.
2. Press **Cmd+Shift+K** — the CapturePopover should appear bottom-right.
3. Wait for the inference engine to process a few captures, then observe ghost notifications resurfacing relevant memories.

---

## Project Layout

```
calm-capture/
├── daemon/                  # Rust workspace (daemon + nm-host crates)
├── extension/               # Chrome Extension (Manifest V3)
├── inference/               # Python inference engine
│   ├── inference_engine.py
│   └── requirements.txt
├── overlay/                 # Swift/AppKit overlay app
│   ├── Package.swift
│   └── Sources/CorteonOverlay/
│       ├── main.swift
│       ├── AppDelegate.swift
│       ├── GhostPanel.swift
│       ├── GhostNotificationView.swift
│       ├── MarginOverlayView.swift
│       ├── CapturePopoverView.swift
│       └── WebSocketClient.swift
├── com.corteon.daemon.plist # LaunchAgent template
├── com.corteon.capture.json # Chrome NM host manifest template
├── install.sh               # One-shot installer
└── start_inference.sh       # Inference engine launcher with venv management
```

---

## Troubleshooting

### Daemon not starting

```bash
# Check daemon status
launchctl list com.corteon.daemon

# View logs
tail -f /tmp/corteon-daemon.log

# Reload manually
launchctl unload ~/Library/LaunchAgents/com.corteon.daemon.plist
launchctl load -w ~/Library/LaunchAgents/com.corteon.daemon.plist
```

### Native Messaging not working

1. Confirm the extension ID in `com.corteon.capture.json` matches Chrome.
2. Verify the NM host binary path is correct:
   ```bash
   cat ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/com.corteon.capture.json
   ```
3. The `corteon-nm-host` binary must be executable:
   ```bash
   chmod +x daemon/target/release/corteon-nm-host
   ```

### Overlay not appearing

```bash
# Run directly to see errors
./overlay/.build/release/CorteonOverlay

# Check Accessibility permissions
# System Settings → Privacy & Security → Accessibility → add CorteonOverlay
```

### Inference engine import errors

```bash
# Ensure you're inside the venv
source .venv/bin/activate
python -c "import spacy; spacy.load('en_core_web_sm'); print('OK')"
```

### WebSocket connection refused

The daemon must be running before starting the inference engine or overlay. Check:

```bash
lsof -i :9741
```

---

## IPC Protocol (WebSocket ws://localhost:9741/ui)

All messages are JSON objects with a `type` discriminator.

### Daemon → Overlay / Inference

| `type` | Description | Key fields |
|--------|-------------|------------|
| `capture_complete` | Page captured | `capture_id`, `title`, `word_count`, `prediction_error_score` |
| `resurface` | Memory resurfaced | `capture_id`, `title`, `excerpt`, `reason` |
| `toast` | Brief notification | `message` |

### Overlay → Daemon

| `type` | Description | Key fields |
|--------|-------------|------------|
| `ui_feedback` | User interaction with notification | `capture_id`, `feedback` (`clicked`\|`dismissed`\|`ignored`) |
| `user_note` | Quick note attached to capture | `capture_id`, `note` |

---

## License

MIT — see LICENSE file.
