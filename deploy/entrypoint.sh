#!/usr/bin/env bash
# Start TALO inside the container: database on first boot, models in the background, then the three processes.
# If any one of them stops, the container exits and Docker restarts it (restart: unless-stopped).
set -euo pipefail
cd /app

# Guidance documents: refresh from the image every start, so a new image brings new guidance.
mkdir -p data/reference
cp -R seed/reference/. data/reference/

# Database: create the synthetic demo set only when there is none. Never on later starts: that would overwrite
# farms officers have edited (the API upgrades the schema of an existing database by itself).
if [ ! -f "${CROP_PILOT_DB:-data/database.db}" ]; then
  python -m crop_pilot.database.init_db
fi

# Models: pulled in the background. Until they are ready the agent falls back to the fixed rules, as designed.
python deploy/pull_models.py &

python -m uvicorn crop_pilot.api.main:app --host 0.0.0.0 --port 8000 --proxy-headers &
api=$!
python -m uvicorn crop_pilot.api.voice_hooks:app --host 0.0.0.0 --port 8001 --proxy-headers &
hooks=$!
streamlit run frontend/app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true \
  --browser.gatherUsageStats false &
desk=$!
trap 'kill $api $hooks $desk 2>/dev/null' TERM INT EXIT

# The model pull may finish and exit normally; only the three servers keep the container alive.
while kill -0 "$api" 2>/dev/null && kill -0 "$hooks" 2>/dev/null && kill -0 "$desk" 2>/dev/null; do
  sleep 5
done
echo "A TALO process stopped; exiting so Docker restarts the container." >&2
exit 1
