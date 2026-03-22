#!/bin/bash
# Launch the YouTube → 小红书 converter app
cd "$(dirname "$0")"

# Create venv if it doesn't exist
if [ ! -d .venv ]; then
    echo "Setting up virtual environment..."
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
fi

echo "Starting app at http://localhost:8501"
.venv/bin/streamlit run app.py
