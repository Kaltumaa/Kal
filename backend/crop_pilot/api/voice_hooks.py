"""Public webhooks for Africa's Talking Voice. The ONLY app to expose to the internet (ngrok http 8001).

The main API (:8000) has the officer's approve buttons and no login, so it must stay on 127.0.0.1. This app has two
routes and nothing else:

    POST /voice/callback?t=TOKEN   the one carrier webhook: pick-up, keypresses (dtmfDigits) and hang-up. Set it as the
                                   voice number's callback URL in the Africa's Talking dashboard; our <GetDigits>
                                   points back to it too.
    POST /voice/dtmf?t=TOKEN       same handler, kept as an alias

The same `router` is mounted on the main API (127.0.0.1:8000) so the internal carrier simulator can post to it
without a second process.

Africa's Talking does not sign its requests, so every request must carry VOICE_WEBHOOK_TOKEN and a sessionId we
placed ourselves; anything else gets <Reject/> or 403.

Run:  make voice-hooks     (uvicorn crop_pilot.api.voice_hooks:app --port 8001)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.parse import parse_qs

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response

from crop_pilot.database.init_db import ensure_schema
from crop_pilot.database.db import connect
from crop_pilot.dispatch import voice_calls


@asynccontextmanager
async def lifespan(_app):
    with connect() as conn:
        ensure_schema(conn)
    yield


router = APIRouter()
MAX_BODY = 16_000


async def _form(request: Request) -> dict:
    if not voice_calls.token_ok(request.query_params.get("t")):
        raise HTTPException(403, detail="forbidden")
    body = (await request.body())[:MAX_BODY].decode("utf-8", "replace")
    return {k: v[0] for k, v in parse_qs(body).items()}


def _xml(text: str) -> Response:
    return Response(content=text, media_type="application/xml")


@router.post("/voice/callback")
@router.post("/voice/dtmf")
async def callback(request: Request):
    return _xml(voice_calls.handle_callback(await _form(request)))


app = FastAPI(title="Mkulima Hub voice webhooks", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health():
    return {"ok": True, "channel": voice_calls.status()["channel"]}
