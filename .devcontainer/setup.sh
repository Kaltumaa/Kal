#!/usr/bin/env bash
# Runs once when the codespace is built.
set -euo pipefail
pip install --user -r requirements.lock
# Ollama's official installer, pinned to the version TALO is tested with (deploy/docker-compose.yml uses the same).
curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=0.40.4 sh
