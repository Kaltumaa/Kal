#!/usr/bin/env bash
# Starts Ollama and the API privately, then the desk on the Space's public port.
set -e
cd /home/node/app
ollama serve >/tmp/ollama.log 2>&1 &
for i in $(seq 1 60); do curl -sf http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 1; done
.venv/bin/python -m uvicorn crop_pilot.api.main:app --host 127.0.0.1 --port 8000 &
for i in $(seq 1 60); do curl -sf http://127.0.0.1:8000/health >/dev/null && break; sleep 1; done
# CORS/XSRF off: the Space serves the app inside an iframe, which otherwise breaks photo uploads.
exec .venv/bin/streamlit run frontend/app.py --server.address 0.0.0.0 --server.port 7860 \
    --server.headless true --browser.gatherUsageStats false \
    --server.enableCORS false --server.enableXsrfProtection false
