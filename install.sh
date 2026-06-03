#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Calm Capture – install.sh
# Installs the daemon LaunchAgent, Native Messaging host manifests, and prints
# setup instructions.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

BOLD=$(tput bold 2>/dev/null || true)
RESET=$(tput sgr0 2>/dev/null || true)
GREEN=$(tput setaf 2 2>/dev/null || true)
YELLOW=$(tput setaf 3 2>/dev/null || true)
RED=$(tput setaf 1 2>/dev/null || true)
CYAN=$(tput setaf 6 2>/dev/null || true)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Directories ───────────────────────────────────────────────────────────────

CORTEON_DIR="$HOME/.corteon"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
CHROME_NM_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
FIREFOX_NM_DIR="$HOME/Library/Application Support/Mozilla/NativeMessagingHosts"

DAEMON_BINARY="$SCRIPT_DIR/daemon/target/release/corteon-daemon"
NM_HOST_BINARY="$SCRIPT_DIR/daemon/target/release/corteon-nm-host"

PLIST_SRC="$SCRIPT_DIR/com.corteon.daemon.plist"
PLIST_DST="$LAUNCH_AGENTS/com.corteon.daemon.plist"

CHROME_MANIFEST_SRC="$SCRIPT_DIR/com.corteon.capture.json"
CHROME_MANIFEST_DST="$CHROME_NM_DIR/com.corteon.capture.json"
FIREFOX_MANIFEST_DST="$FIREFOX_NM_DIR/com.corteon.capture.json"

# ── Helpers ───────────────────────────────────────────────────────────────────

step()    { echo "${CYAN}▶ ${BOLD}$*${RESET}"; }
ok()      { echo "${GREEN}✓ $*${RESET}"; }
warn()    { echo "${YELLOW}⚠ $*${RESET}"; }
error()   { echo "${RED}✗ $*${RESET}"; }
divider() { echo "────────────────────────────────────────────────────"; }

# ── Preflight checks ──────────────────────────────────────────────────────────

divider
echo "${BOLD}Calm Capture – Installer${RESET}"
divider

# Rust / cargo
step "Checking Rust toolchain…"
if command -v cargo &>/dev/null; then
    CARGO_VERSION=$(cargo --version)
    ok "Found $CARGO_VERSION"
else
    warn "cargo not found."
    echo "  Install Rust with:"
    echo "    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    echo "  Then re-run this script."
fi

# Python
step "Checking Python 3…"
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 --version)
    ok "Found $PY_VERSION"
else
    warn "python3 not found. Required for the inference engine."
fi

# Daemon binary existence (not fatal – user may build later)
step "Checking daemon binary…"
if [[ -f "$DAEMON_BINARY" ]]; then
    ok "Daemon binary found at $DAEMON_BINARY"
else
    warn "Daemon binary not found at $DAEMON_BINARY"
    echo "  Build it first with:"
    echo "    cd \"$SCRIPT_DIR/daemon\" && cargo build --release"
fi

# ── Create ~/.corteon directory ────────────────────────────────────────────────

step "Creating ~/.corteon …"
mkdir -p "$CORTEON_DIR"
ok "~/.corteon ready"

# ── LaunchAgent ───────────────────────────────────────────────────────────────

step "Installing LaunchAgent plist…"
mkdir -p "$LAUNCH_AGENTS"

# Patch daemon path into the plist before copying
PLIST_TMP=$(mktemp /tmp/com.corteon.daemon.XXXXXX.plist)
sed "s|CORTEON_DAEMON_PATH|${DAEMON_BINARY}|g" "$PLIST_SRC" > "$PLIST_TMP"
cp "$PLIST_TMP" "$PLIST_DST"
rm -f "$PLIST_TMP"
ok "Installed $PLIST_DST"

# Unload any existing instance, then load
if launchctl list com.corteon.daemon &>/dev/null 2>&1; then
    step "Unloading existing daemon…"
    launchctl unload "$PLIST_DST" 2>/dev/null || true
fi

if [[ -f "$DAEMON_BINARY" ]]; then
    step "Loading daemon via launchctl…"
    launchctl load -w "$PLIST_DST"
    ok "Daemon loaded (com.corteon.daemon)"
else
    warn "Skipping launchctl load – daemon binary missing. Run after building."
fi

# ── Native Messaging hosts ────────────────────────────────────────────────────

step "Installing Chrome Native Messaging host manifest…"
mkdir -p "$CHROME_NM_DIR"
sed "s|NM_HOST_BINARY_PATH|${NM_HOST_BINARY}|g" "$CHROME_MANIFEST_SRC" > "$CHROME_MANIFEST_DST"
ok "Chrome manifest installed at $CHROME_MANIFEST_DST"

step "Installing Firefox Native Messaging host manifest…"
mkdir -p "$FIREFOX_NM_DIR"
# Firefox uses slightly different format – reuse same binary path substitution
sed "s|NM_HOST_BINARY_PATH|${NM_HOST_BINARY}|g" "$CHROME_MANIFEST_SRC" > "$FIREFOX_MANIFEST_DST"
ok "Firefox manifest installed at $FIREFOX_MANIFEST_DST"

# ── Summary ───────────────────────────────────────────────────────────────────

divider
echo "${BOLD}${GREEN}Installation complete!${RESET}"
divider
echo ""
echo "Next steps:"
echo ""
echo "  1. ${BOLD}Build the Rust daemon (if not done):${RESET}"
echo "     cd \"$SCRIPT_DIR/daemon\" && cargo build --release"
echo ""
echo "  2. ${BOLD}Build the Swift overlay:${RESET}"
echo "     cd \"$SCRIPT_DIR/overlay\" && swift build -c release"
echo ""
echo "  3. ${BOLD}Install Python deps:${RESET}"
echo "     cd \"$SCRIPT_DIR\" && bash start_inference.sh --install-only"
echo ""
echo "  4. ${BOLD}Load the Chrome extension:${RESET}"
echo "     Open chrome://extensions → Enable Developer Mode → Load Unpacked"
echo "     → select \"$SCRIPT_DIR/extension\""
echo ""
echo "  5. ${BOLD}Start the overlay:${RESET}"
echo "     \"$SCRIPT_DIR/overlay/.build/release/CorteonOverlay\" &"
echo ""
echo "  6. ${BOLD}Start the inference engine:${RESET}"
echo "     bash \"$SCRIPT_DIR/start_inference.sh\""
echo ""
echo "  7. Press ${BOLD}Cmd+Shift+K${RESET} on any web page to test."
echo ""
divider
