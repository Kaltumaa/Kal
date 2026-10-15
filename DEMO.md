# Demo video script (< 3 minutes, one unedited take)

The brief asks for **an unedited agent run with tool calls visible, not slides**, and the rubric asks to show **where it
fails**. On a CPU-only laptop one live run takes ~1–2 minutes, so start the run early and narrate while it works.

**Before recording:** `make db` (clean queue), then `make run`, open http://127.0.0.1:8501 in Chrome. Pre-run `HH-DS-006`
(the locked draft) and `HH-DS-007` (a potato SPRAY, used at 2:35) so both are already in the queue. In a second terminal, show the audit log live:

```bash
while true; do clear; sqlite3 -header -column data/database.db "select id, server, tool, status, round(latency_ms) ms, actor, approved_by from tool_calls order by id desc limit 14"; sleep 2; done
```

| Time | Screen | Say |
|---|---|---|
| 0:00 | **Dashboard** | "Crop-Pilot drafts Plant, Spray or Hold advice for the Dagoretti South extension desk from rainfall and verified pest signals. Waithaka has a washout warning; Riruta's planting window is open. Everything runs on this laptop: SQLite plus Qwen 2.5 on Ollama." |
| 0:15 | **Review queue → New draft** → `HH-DS-003` → **Run agent** | "One household, a maize plot in Mutu-ini." |
| 0:20 | Terminal with the live log | "The local model picks its own tools on our MCP server: plot context, which scrubs the record; rainfall outlook, which computes a spray-safety index; pest reports, which scores verified outbreaks. It reads guidance through the official filesystem MCP server. Then `draft_advisory` writes to a staging queue. That is its only write." |
| 1:10 | Draft detail → **Evidence** tab | "SPRAY: verified Fall Armyworm 0.1 km away, dry window. Every number cites a record. **Here is where the model fails:** the flag `corrected_args:get_pest_reports` means the 3B model passed the wrong growth stage, and the harness re-ran the call with the calendar-derived stage. It also skipped the guidance file, so that was auto-filled. We report this in EVALS.md as unfixed." |
| 1:40 | **Agent steps** tab | "Every step, with its latency." |
| 1:50 | Select `HH-DS-006` (Security lock) | "This household's notes hide a prompt injection telling the agent to approve and SMS every farmer. It was redacted before any model saw it. The draft cannot be signed." |
| 2:05 | Back to HH-DS-003 → **Message & signature**: type a name, tick, **Sign & send** | "Nothing leaves without a named officer. The database itself refuses an unsigned approval." |
| 2:20 | **Sent messages**, then the terminal's `[audit]` lines | "The SMS is queued (simulated), and every logged action of the run now carries the officer's name." |
| 2:35 | **Dashboard → Rainfall numbers → record a new forecast** for Uthiru (90 mm, storm HIGH), then open the `HH-DS-007` draft in the queue | "Rainfall estimates shift. A storm forecast just arrived, so this potato SPRAY draft is now blocked: it cannot be signed until the agent re-runs with the new forecast." |
| 2:50 | `EVALS.md` | "Eight task types, five runs each, with the failures we have not fixed. Link below." |

Upload as **public on YouTube or Vimeo** and paste the link into the submission form and the README.
