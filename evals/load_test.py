"""Load test: does delivery hold as usage grows? Runs on a temporary COPY of the database, never the real one.

    make load-test                       (or: PYTHONPATH=backend python evals/load_test.py --farms 100 1000 5000)

A. Scale: the weekly plan (every farm's Plant / Spray / Hold rule preview) at 100, 1,000 and 5,000 farms.
B. Concurrency: 25 officers hitting the API at once (500 requests: dashboard, drafts, farm list, farm profiles)
   against a 1,000-farm database; p50 / p95 / max latency, errors and requests per second.
The agent's per-household time with the local model is measured separately in EVALS.md.
Results are printed and saved to evals/results/load-<time>.md.
"""
from __future__ import annotations

import argparse
import os
import random
import shutil
import socket
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("CROP_PILOT_LIVE_WEATHER", "0")      # no network: measure TALO, not the weather providers
os.environ.setdefault("VOICE_AUTO_SIMULATE", "0")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import Request  # noqa: E402

from crop_pilot import config  # noqa: E402
from crop_pilot.database.db import connect  # noqa: E402
from crop_pilot.database.init_db import init_db  # noqa: E402

RESULTS = ROOT / "evals" / "results"


def _grow(db: Path, farms: int) -> int:
    """Clone the demo farms (same wards, crops and records) until the database holds `farms` farms."""
    with connect(db) as conn:
        base = [dict(r) for r in conn.execute("SELECT * FROM plots WHERE household_id NOT LIKE 'HH-LT-%'")]
        have = conn.execute("SELECT COUNT(*) FROM plots").fetchone()[0]
        cols = list(base[0])
        rows = []
        for i in range(have, farms):
            r = dict(base[i % len(base)])
            r["household_id"] = f"HH-LT-{i:05d}"
            r["phone"] = None
            r["cell_id"] = None
            rows.append(tuple(r[c] for c in cols))
        if rows:
            conn.executemany(f"INSERT INTO plots ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", rows)
        return conn.execute("SELECT COUNT(*) FROM plots").fetchone()[0]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(port: int) -> uvicorn.Server:
    from crop_pilot.api import access, main

    def officer(req: Request) -> None:      # load test acts as signed-in officers; sign-in is covered by tests
        req.state.user = {"id": 0, "role": "extension_officer", "full_name": "Load Test", "household_id": None,
                          "active": 1}
    main.app.dependency_overrides[access.guard] = officer
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning",
                                           lifespan="on"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.1)
    raise RuntimeError("test server did not start")


def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--farms", type=int, nargs="+", default=[100, 1000, 5000])
    ap.add_argument("--officers", type=int, default=25)
    ap.add_argument("--requests", type=int, default=500)
    ap.add_argument("--concurrency-farms", type=int, default=1000)
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="talo-load-"))
    db = work / "load.db"
    init_db(db, reset=True)
    config.DB_PATH = db
    config.CHECKPOINT_DB_PATH = work / "checkpoints.db"
    port = _free_port()
    server = _serve(port)
    base = f"http://127.0.0.1:{port}"
    lines = []
    try:
        # A. scale -----------------------------------------------------------------------------------------------
        scale = []
        with httpx.Client(base_url=base, timeout=600) as c:
            for n in sorted(args.farms):
                total = _grow(db, n)
                t = time.perf_counter()
                plan = c.get("/farms/plan")
                s = time.perf_counter() - t
                plan.raise_for_status()
                scale.append((total, len(plan.json()), s))
                print(f"A. weekly plan for {total} farms: {s:.2f} s ({total / s:.0f} farms/s)")

        # B. concurrency -----------------------------------------------------------------------------------------
        shutil.copy(db, work / "conc.db")
        config.DB_PATH = work / "conc.db"
        with connect(config.DB_PATH) as conn:
            conn.execute("DELETE FROM plots WHERE household_id LIKE 'HH-LT-%' AND CAST(substr(household_id, 7) AS "
                         "INTEGER) >= ?", (args.concurrency_farms,))
            hids = [r[0] for r in conn.execute("SELECT household_id FROM plots")]
        paths = ["/overview", "/advisories", "/farms"] + [f"/households/{h}/profile" for h in hids[:50]]
        random.seed(7)
        jobs = [random.choice(paths) for _ in range(args.requests)]
        lat, errors = [], 0
        lock = threading.Lock()

        def hit(path: str) -> None:
            nonlocal errors
            t = time.perf_counter()
            try:
                r = httpx.get(base + path, timeout=120)
                bad = r.status_code >= 400
            except httpx.HTTPError:
                bad = True
            with lock:
                lat.append((time.perf_counter() - t) * 1000)
                errors += bad
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.officers) as pool:
            list(pool.map(hit, jobs))
        wall = time.perf_counter() - t0
        print(f"B. {len(jobs)} requests from {args.officers} officers at once: p50 {_pct(lat, 50):.0f} ms, "
              f"p95 {_pct(lat, 95):.0f} ms, errors {errors}")

        when = datetime.now(timezone.utc)
        lines = [f"# Load test, {when.strftime('%Y-%m-%d %H:%M UTC')}", "",
                 "On a temporary copy of the database (demo farms cloned with the same wards, crops and records), on "
                 "this laptop, live weather off.", "",
                 "## A. Scale: the weekly plan (every farm's rule preview)", "",
                 "| Farms | Planned | Seconds | Farms per second |", "|---|---|---|---|"]
        lines += [f"| {t:,} | {p:,} | {s:.2f} | {t / s:,.0f} |" for t, p, s in scale]
        lines += ["", f"## B. Concurrency: {args.officers} officers at once, {len(jobs)} requests, "
                      f"{len(hids):,}-farm database", "",
                  "| p50 | p95 | max | errors | requests/s |", "|---|---|---|---|---|",
                  f"| {_pct(lat, 50):.0f} ms | {_pct(lat, 95):.0f} ms | {max(lat):.0f} ms | {errors} | "
                  f"{len(jobs) / wall:.1f} |", "",
                  "## Not covered here", "",
                  "- The agent itself (local model): about 80 s per household on this CPU, one at a time (EVALS.md). "
                  "A desk drafts in batches, so this is the bottleneck; more officers' desks means more machines or a GPU.",
                  "- SMS / WhatsApp / M-Pesa throughput is set by those providers, not by TALO."]
    finally:
        server.should_exit = True
    text = "\n".join(lines) + "\n"
    print("\n" + text)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"load-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.md"
    out.write_text(text)
    print(f"Saved {out}")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
