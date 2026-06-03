#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Calm Capture – start_inference.sh
# Activates (or creates) a Python virtual-env, installs dependencies on first
# run, and launches the inference engine.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

BOLD=$(tput bold 2>/dev/null || true)
RESET=$(tput sgr0 2>/dev/null || true)
GREEN=$(tput setaf 2 2>/dev/null || true)
YELLOW=$(tput setaf 3 2>/dev/null || true)
CYAN=$(tput setaf 6 2>/dev/null || true)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
REQUIREMENTS="$SCRIPT_DIR/inference/requirements.txt"
ENGINE="$SCRIPT_DIR/inference/inference_engine.py"

step()  { echo "${CYAN}▶ ${BOLD}$*${RESET}"; }
ok()    { echo "${GREEN}✓ $*${RESET}"; }
warn()  { echo "${YELLOW}⚠ $*${RESET}"; }

# ── Parse flags ───────────────────────────────────────────────────────────────

INSTALL_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --install-only) INSTALL_ONLY=true ;;
    esac
done

# ── Locate Python 3.11+ ───────────────────────────────────────────────────────

find_python() {
    for candidate in python3.11 python3.12 python3.13 python3; do
        if command -v "$candidate" &>/dev/null; then
            local ver
            ver=$("$candidate" -c "import sys; print(sys.version_info >= (3,11))" 2>/dev/null || echo "False")
            if [[ "$ver" == "True" ]]; then
                echo "$candidate"
                return
            fi
        fi
    done
    echo ""
}

PYTHON=$(find_python)
if [[ -z "$PYTHON" ]]; then
    echo "Error: Python 3.11 or newer is required but was not found." >&2
    echo "Install via: brew install python@3.11" >&2
    exit 1
fi
ok "Using Python: $($PYTHON --version)"

# ── Create venv if needed ─────────────────────────────────────────────────────

if [[ ! -d "$VENV_DIR" ]]; then
    step "Creating virtual environment at .venv …"
    "$PYTHON" -m venv "$VENV_DIR"
    ok "Virtual environment created"
fi

# ── Activate venv ─────────────────────────────────────────────────────────────

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"
ok "Activated .venv"

# ── Install / upgrade dependencies ────────────────────────────────────────────

if [[ -f "$REQUIREMENTS" ]]; then
    step "Installing Python dependencies…"
    pip install --quiet --upgrade pip
    pip install --quiet -r "$REQUIREMENTS"
    ok "Dependencies installed"

    # Download spaCy model if not already present
    if ! python -c "import spacy; spacy.load('en_core_web_sm')" &>/dev/null 2>&1; then
        step "Downloading spaCy en_core_web_sm model…"
        python -m spacy download en_core_web_sm --quiet
        ok "spaCy model ready"
    else
        ok "spaCy en_core_web_sm already installed"
    fi
else
    warn "No requirements.txt found at $REQUIREMENTS – skipping pip install"
fi

if $INSTALL_ONLY; then
    ok "Install-only mode complete."
    exit 0
fi

# ── Launch inference engine ───────────────────────────────────────────────────

if [[ ! -f "$ENGINE" ]]; then
    echo "Error: inference engine not found at $ENGINE" >&2
    exit 1
fi

step "Starting Calm Capture inference engine…"
echo "  Press Ctrl+C to stop."
echo ""

cd "$SCRIPT_DIR"
exec python "$ENGINE"
