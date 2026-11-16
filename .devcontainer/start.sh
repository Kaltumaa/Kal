#!/usr/bin/env bash
# Starts TALO in a codespace: Ollama, the models (in the background), the API, the webhooks and the Control Desk.
# Runs on every codespace start. Log: /tmp/talo.log   Restart by hand: bash .devcontainer/start.sh
set -uo pipefail
cd "$(dirname "$0")/.."

export PYTHONPATH="$PWD/backend"
export PATH="$HOME/.local/bin:$PATH"
export OLLAMA_HOST=http://127.0.0.1:11434
export CROP_PILOT_TODAY="${CROP_PILOT_TODAY-2026-10-15}"     # demo data's date; set an empty Codespaces secret for real dates
export VOICE_AUTO_SIMULATE="${VOICE_AUTO_SIMULATE:-1}"
# Codespaces gives each port its own https address; the webhooks (8001) get one for Africa's Talking / WhatsApp.
if [ -n "${CODESPACE_NAME:-}" ]; then
  export VOICE_PUBLIC_URL="https://${CODESPACE_NAME}-8001.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
fi

# Stop an earlier copy (a restart), then start fresh.
pkill -f "uvicorn crop_pilot.api" 2>/dev/null
pkill -f "streamlit run frontend/app.py" 2>/dev/null
sleep 1

pgrep -x ollama >/dev/null || (nohup ollama serve > /tmp/ollama.log 2>&1 &)
[ -f data/database.db ] || python -m crop_pilot.database.init_db
python deploy/pull_models.py &

python -m uvicorn crop_pilot.api.main:app --host 127.0.0.1 --port 8000 &
python -m uvicorn crop_pilot.api.voice_hooks:app --host 0.0.0.0 --port 8001 --proxy-headers &
# Codespaces' port proxy breaks Streamlit's upload check (photo uploads fail with 403), so XSRF is off here only.
# Sign-in uses bearer tokens held server-side, not cookies, so this does not open the API to cross-site requests.
streamlit run frontend/app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true \
  --browser.gatherUsageStats false --server.enableCORS false --server.enableXsrfProtection false &

echo "TALO starting: Control Desk on port 8501 (Ports tab). Models: grep models /tmp/talo.log"
wait
