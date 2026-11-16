# TALO in GitHub Codespaces (free)

A codespace is a free Linux machine from GitHub. This one runs all of TALO, including the local AI models, and gives
it a public HTTPS link for judges.

**Free allowance:** 120 core-hours a month on a free GitHub account, about **30 hours** on the 4-core machine TALO
needs. The codespace stops by itself when idle, so start it before a demo and stop it after
(github.com/codespaces → ⋯ → Stop).

## Start it

1. On the repo page: **Code → Codespaces → ⋯ → New with options**.
   Branch: the one with TALO; **Machine type: 4-core, 16 GB**. Then **Create codespace**.
2. The first build takes about 5 minutes (Python packages, Ollama). TALO then starts by itself.
3. Open the **Ports** tab at the bottom. Port **8501 (TALO Control Desk)** appears; click the globe to open it.
4. **Share it:** right-click port 8501 → **Port visibility → Public**. Its address
   (`https://<name>-8501.app.github.dev`) is the link for judges. Ports 8000 and 11434 stay private.
5. The AI models download in the background (about 2.3 GB, a few minutes). Until then drafts come from the fixed
   rules. Check in the terminal:
   ```bash
   grep models /tmp/talo.log
   ```
   Ready when it shows `qwen2.5:3b ready` and `moondream ready`.

## Keys (optional)

The codespace has no `.env`; keys are **Codespaces secrets**, which reach the app as environment variables and never
go into the repo. On GitHub: **Settings → Codespaces → Secrets → New secret**, give it access to this repository.
Use the same names as `.env.example`, for example `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`, `MPESA_PASSKEY`,
`MPESA_SHORTCODE`, `MPESA_ENV`, `AT_USERNAME`, `AT_API_KEY`, `JWT_SECRET`. Restart the codespace after adding them.
Without keys, every provider runs on its built-in simulator.

## Good to know

- **Accounts:** a new codespace starts with the demo farms and no accounts. Sign up on the sign-in page.
- **Webhooks:** to receive WhatsApp or voice callbacks, make port 8001 public too and give the providers
  `https://<name>-8001.app.github.dev/whatsapp/webhook` (or `/voice/callback?t=<VOICE_WEBHOOK_TOKEN>`).
  M-Pesa results come back to the main API, which stays private here, so payments show as sent but not confirmed;
  the server setup in `deploy/` receives them.
- **Restart TALO** without restarting the codespace: `bash .devcontainer/start.sh`.
- **Data** lives in the codespace and is kept between stops, but is lost if the codespace is deleted.
