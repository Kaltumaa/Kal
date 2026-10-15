# Hugging Face Space (Docker SDK) for the public demo.
# Builds straight from the public GitHub repo, bakes in both open-weights models, and serves the
# Streamlit desk on :7860 (the Space's port). The API and Ollama stay private inside the container.
FROM node:22-bookworm-slim

ARG REPO=https://github.com/Kaltumaa/Kal.git
ARG BRANCH=main
ARG MODEL=qwen2.5:3b
ARG VISION_MODEL=moondream
ARG FS_MCP_PACKAGE=@modelcontextprotocol/server-filesystem@2026.8.31

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git zstd procps \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://ollama.com/install.sh | sh

# Hugging Face runs the container as uid 1000, which is the image's "node" user.
USER node
ENV HOME=/home/node \
    PATH=/home/node/.local/bin:$PATH \
    OLLAMA_HOST=127.0.0.1:11434 \
    OLLAMA_MODELS=/home/node/.ollama/models \
    OLLAMA_MODEL=${MODEL} \
    CROP_PILOT_VISION_MODEL=${VISION_MODEL} \
    CROP_PILOT_TODAY=2026-10-15 \
    CROP_PILOT_LLM_TIMEOUT=300 \
    PYTHONPATH=/home/node/app/backend
WORKDIR /home/node/app

RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && git clone --depth 1 --branch ${BRANCH} ${REPO} . \
    && uv venv --python 3.12 .venv \
    && uv pip install --python .venv -r requirements.lock \
    && .venv/bin/python -m crop_pilot.database.init_db --reset \
    && npm cache add ${FS_MCP_PACKAGE}

# Pull the models at build time so the Space starts without a multi-GB download.
RUN (ollama serve >/tmp/ollama-build.log 2>&1 &) \
    && for i in $(seq 1 30); do curl -sf http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 1; done \
    && ollama pull ${MODEL} && ollama pull ${VISION_MODEL}

COPY --chown=node:node start.sh /home/node/start.sh
EXPOSE 7860
CMD ["bash", "/home/node/start.sh"]
