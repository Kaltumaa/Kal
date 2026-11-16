# Deploying TALO on a server

One Linux server runs everything: the Control Desk, the local AI models, the webhooks and HTTPS.

```
internet ──443──▶ Caddy (HTTPS, automatic certificate)
                    ├─ /voice/callback, /voice/dtmf, /whatsapp/webhook ─▶ webhooks  :8001
                    ├─ /api/payments/mpesa/callback, /api/payments/card/* ─▶ API    :8000
                    └─ everything else ─────────────────────────────────▶ Control Desk :8501
                 API :8000 (the rest of it) ─ private, only inside the server
                 Ollama (Qwen 2.5 3B + Moondream) ─ private
```

## Where

- **Judging and demos:** any VPS with **4 vCPU, 8 GB RAM, 40 GB disk**, Ubuntu 24.04. That runs the 3B agent model
  and the photo model (one at a time). It costs about $10–40 a month, in line with the $40 in `FACT_SHEET.md`.
- **Murang'a pilot:** host **in Kenya** (a Nairobi data centre or a Kenyan cloud). Kenya's Data Protection Act asks
  for data processed for the state's strategic interests to be processed in Kenya or have a copy there, and a county
  extension service holding farmers' phones and plots may fall under that. Register with the ODPC (the county as
  data controller, TALO as data processor).

## First deploy (about 30 minutes, most of it the model download)

1. **Server:** create the VPS, then open ports 22, 80 and 443 only:
   ```bash
   sudo ufw allow 22 && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
   ```
2. **Address:** point a domain's A record at the server's IP. No domain yet? Use `1-2-3-4.sslip.io` (your IP with
   dashes); it resolves to the server and gets a real certificate.
3. **Docker:**
   ```bash
   curl -fsSL https://get.docker.com | sudo sh
   ```
4. **Code and keys:**
   ```bash
   git clone <your repo URL> talo && cd talo
   cp .env.example .env && nano .env
   ```
   Set at least `TALO_DOMAIN`, `JWT_SECRET` (`openssl rand -hex 32`), `VOICE_WEBHOOK_TOKEN`,
   `WHATSAPP_VERIFY_TOKEN` and `MPESA_CALLBACK_TOKEN` (`openssl rand -hex 16` each), plus whichever provider keys you
   have. `.env` stays on the server: it is git-ignored and never copied into the image (`.dockerignore`).
5. **Start:**
   ```bash
   docker compose --env-file .env -f deploy/docker-compose.yml up -d --build
   ```
6. **Watch it come up:** the desk is ready in about a minute; the models download in the background (the agent uses
   the fixed rules until they finish):
   ```bash
   docker compose -f deploy/docker-compose.yml logs -f talo | grep -E "models|Uvicorn|ERROR"
   ```
   Done when the log says `[models] qwen2.5:3b ready` and `[models] moondream ready`. Then open
   `https://<TALO_DOMAIN>`.

## Point the providers at the server

| Provider | Where | URL |
|---|---|---|
| Africa's Talking voice | Voice → your number → callback URL | `https://<TALO_DOMAIN>/voice/callback?t=<VOICE_WEBHOOK_TOKEN>` |
| WhatsApp (Meta) | App → WhatsApp → Configuration → Webhook | `https://<TALO_DOMAIN>/whatsapp/webhook`, verify token = `WHATSAPP_VERIFY_TOKEN` |
| M-Pesa Daraja | nothing to do | sent with every payment request: `https://<TALO_DOMAIN>/api/payments/mpesa/callback?t=…` |
| Stripe / Flutterwave | Webhooks | `https://<TALO_DOMAIN>/api/payments/card/webhook` |

Then run the integration check on the server:

```bash
docker compose -f deploy/docker-compose.yml exec talo python -m crop_pilot.integrations_check
```

## Accounts

The server starts with the synthetic demo farms and **no accounts**. Officers, farmers and institutions sign up on
the sign-in page. Don't reuse the short local passwords from `data/my_logins.md` on a public server: the app's
10-character minimum applies there.

## Day to day

| Task | Command |
|---|---|
| Update to the latest code | `git pull && docker compose --env-file .env -f deploy/docker-compose.yml up -d --build` |
| Back up the database and photos | `docker run --rm -v talo_talo-data:/d -v "$PWD":/b alpine tar czf /b/talo-backup-$(date +%F).tgz -C /d .` |
| Restart | `docker compose -f deploy/docker-compose.yml restart talo` |
| Logs | `docker compose -f deploy/docker-compose.yml logs -f --tail 100` |

The database, photos and paper-form backup live in the `talo-data` volume; models in `ollama-models`; certificates
in `caddy-data`. Rebuilding the image keeps all three. If one of the three TALO processes stops, the container exits
and Docker restarts it.

## For a real pilot (not the demo)

- Put an empty `CROP_PILOT_TODAY=` in `.env` so the app uses real dates (the demo pins them to the synthetic data).
- Set `VOICE_AUTO_SIMULATE=0` once Africa's Talking voice is live, so calls are placed for real.
- Replace the synthetic farms with Murang'a's own records (`CROP_PILOT_DB` points at a database with the same
  schema, `backend/crop_pilot/database/init_db.py`).
- Back up the database off the server every day.
