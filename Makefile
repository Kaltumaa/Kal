# Crop-Pilot — one command for a stranger:   make
SHELL := /bin/bash
PY_VERSION ?= 3.12
MODEL ?= qwen2.5:3b
VENV := .venv
PY := $(VENV)/bin/python
export PYTHONPATH := $(CURDIR)/backend
export OLLAMA_MODEL := $(MODEL)
# The synthetic dataset is dated around this day; pin it so the demo behaves the same whenever it is run.
export CROP_PILOT_TODAY ?= 2026-10-15
UV := $(shell command -v uv 2>/dev/null || echo $(HOME)/Library/Python/3.9/bin/uv)
OLLAMA := $(shell command -v ollama 2>/dev/null || echo $(HOME)/.local/ollama/ollama)

.PHONY: all setup db model run stop backend frontend test evals evals-quick clean help

all: setup run                     ## install everything, then start backend + frontend

help:
	@grep -E '^[a-z-]+:.*##' Makefile | awk -F':.*## ' '{printf "  make %-12s %s\n", $$1, $$2}'

setup: $(VENV)/.installed db model ## venv + dependencies + database + local model

$(VENV)/.installed: backend/requirements.txt frontend/requirements.txt requirements.lock
	@command -v $(UV) >/dev/null 2>&1 || python3 -m pip install --user uv
	$(UV) venv --python $(PY_VERSION) $(VENV)
	$(UV) pip install --python $(VENV) -r requirements.lock
	@touch $@

db:                                ## (re)create data/database.db with the synthetic household set
	$(PY) -m crop_pilot.database.init_db --reset
	@rm -f data/checkpoints.db

model:                             ## pull the open-weights model into the LOCAL Ollama
	@if [ -x "$(OLLAMA)" ] || command -v ollama >/dev/null; then \
	  (curl -sf http://127.0.0.1:11434/api/tags >/dev/null || (nohup $(OLLAMA) serve >/tmp/ollama.log 2>&1 &) ); sleep 2; \
	  $(OLLAMA) pull $(MODEL); \
	else echo "!! Ollama not found: install from https://ollama.com (the agent falls back to deterministic mode without it)"; fi

run: stop                          ## start API on :8000 and Control Desk on :8501 (Ctrl-C stops both)
	@for port in 8000 8501; do \
	  if lsof -nP -iTCP:$$port -sTCP:LISTEN >/dev/null 2>&1; then \
	    echo "!! Port $$port is used by another program:"; lsof -nP -iTCP:$$port -sTCP:LISTEN | tail -n +2; exit 1; fi; \
	done
	@curl -sf http://127.0.0.1:11434/api/tags >/dev/null || (nohup $(OLLAMA) serve >/tmp/ollama.log 2>&1 &) || true
	@echo ">> Control Desk: http://127.0.0.1:8501   API: http://127.0.0.1:8000/docs   (Ctrl-C to stop)"
	@trap 'kill 0' INT TERM; \
	$(PY) -m uvicorn crop_pilot.api.main:app --host 127.0.0.1 --port 8000 & \
	$(VENV)/bin/streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false; \
	wait

stop:                              ## stop any Crop-Pilot API / Control Desk already running
	@pkill -f "uvicorn crop_pilot.api.main" 2>/dev/null || true
	@pkill -f "streamlit run frontend/app.py" 2>/dev/null || true
	@sleep 1

backend:                           ## API only
	$(PY) -m uvicorn crop_pilot.api.main:app --host 127.0.0.1 --port 8000

frontend:                          ## Control Desk only (expects the API on :8000)
	$(VENV)/bin/streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false

test:                              ## unit + boundary tests
	$(PY) -m pytest -q tests

evals:                             ## 8 tasks x 5 runs on the local model -> evals/results/
	$(PY) evals/run_evals.py --runs 5

evals-quick:                       ## 8 tasks x 1 run, deterministic (no LLM)
	$(PY) evals/run_evals.py --runs 1 --no-llm

clean:                             ## wipe local database, checkpoints and fallback queue
	rm -f data/database.db data/checkpoints.db data/manual_fallback.jsonl
