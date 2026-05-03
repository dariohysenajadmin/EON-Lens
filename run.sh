#!/usr/bin/env bash
# run.sh - one-click launcher for Lens on macOS / Linux.

set -e
cd "$(dirname "$0")"

echo
echo "=== Lens - starting up ==="
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "[error] python3 not found on PATH."
    exit 1
fi

if ! python3 -c "import streamlit" >/dev/null 2>&1; then
    echo "[setup] First run - installing Python dependencies..."
    python3 -m pip install --user -r requirements.txt
fi

echo "Opening Lens at http://localhost:8501"
echo "Press Ctrl+C to stop."
echo

python3 -m streamlit run app.py --browser.gatherUsageStats false
