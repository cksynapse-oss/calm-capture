#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Calm Capture – start_inference.sh
# Launches the Python Inference Engine, API, and Dashboard natively on macOS.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Setting up Python virtual environment..."
cd inference
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt

echo "Starting Inference Engine & API..."
# Stop old processes if running
pkill -f "inference_engine.py" || true
pkill -f "uvicorn api:app" || true
pkill -f "vite" || true

python inference_engine.py > /tmp/corteon-inference.log 2>&1 &
uvicorn api:app --host 0.0.0.0 --port 8000 > /tmp/corteon-api.log 2>&1 &

echo "Starting Dashboard..."
cd ../dashboard
npm install
npm run dev > /tmp/corteon-dashboard.log 2>&1 &

echo ""
echo "✅ Stack is running locally!"
echo "   Dashboard UI:  http://localhost:5173"
echo "   Inference API: http://localhost:8000"
echo "   WebSocket:     ws://localhost:8765"
echo ""
echo "To view logs:"
echo "  tail -f /tmp/corteon-inference.log"
echo "  tail -f /tmp/corteon-api.log"
echo "  tail -f /tmp/corteon-dashboard.log"

