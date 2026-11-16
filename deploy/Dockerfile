# TALO on a server: API (:8000, private), public webhooks (:8001) and the Control Desk (:8501), in one image.
# Built from the repo root:  docker compose --env-file .env -f deploy/docker-compose.yml up -d --build
FROM python:3.12.16-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    PIP_NO_CACHE_DIR=1

# Node.js runs the official filesystem MCP server (npx); tini reaps the three child processes cleanly.
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs npm tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.lock .
RUN pip install -r requirements.lock

RUN useradd --create-home --uid 10001 talo
COPY --chown=talo:talo backend ./backend
COPY --chown=talo:talo frontend ./frontend
COPY --chown=talo:talo .streamlit ./.streamlit
# Guidance documents ship with the image and are copied into the data volume on every start (see entrypoint).
COPY --chown=talo:talo data/reference ./seed/reference
COPY --chown=talo:talo deploy/entrypoint.sh deploy/pull_models.py ./deploy/
RUN mkdir -p /app/data && chown talo:talo /app/data
USER talo

# Warm npm's cache with the pinned MCP server (same version as config.py) so the first agent run doesn't wait.
RUN npm cache add "$(python -c "from crop_pilot import config; print(config.FS_MCP_PACKAGE)")"

EXPOSE 8001 8501
ENTRYPOINT ["/usr/bin/tini", "--", "bash", "/app/deploy/entrypoint.sh"]
