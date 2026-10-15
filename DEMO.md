# Demo video script (< 3 minutes, one unedited take)

The brief asks for **an unedited agent run with tool calls visible, not slides**. On a CPU-only laptop one live run takes
~1–2 minutes, so start the run at 0:20 and narrate the screen while it works.

**Before recording:** `make db` (clean queue), then `make run`. In a second terminal window you will show the
audit log live:

```bash
while true; do clear; sqlite3 -header -column data/database.db "select id, server, tool, status, round(latency_ms) ms, actor, approved_by from tool_calls order by id desc limit 14"; sleep 2; done
```

(Or skip the terminal and open the **📈 Agent telemetry** tab after the run.)

| Time | Screen | Say |
|---|---|---|
| 0:00 | Control Desk header | "Crop-Pilot is a climate-smart advisory co-pilot for the Dagoretti South extension desk. The agent drafts Plant, Spray or Hold advice. A named officer decides. Everything runs locally: SQLite, plus Qwen 2.5 on Ollama." |
| 0:15 | Select `HH-DS-003` → **Run agent** | "I'm asking it to draft advice for one household." |
| 0:20 | Switch to the terminal running the loop | "Here are the live tool calls. The local model decides what to call on our MCP server: plot context, which scrubs the record; rainfall outlook, which computes a spray-safety index; pest reports, which scores verified outbreaks by distance and age. It reads guidance through the official filesystem MCP server, our third-party server. Then `draft_advisory` writes to a staging queue. That is the only write it has." |
| 1:30 | Back to the browser: the SPRAY card | "Verified Fall Armyworm 0.1 km away, a dry window, spray index 95. Every number cites its record: plot, weather cache, pest alert #1, guidance file. The unverified WhatsApp report was ignored." Open **Agent trace**. |
| 1:50 | `HH-DS-006` red card (pre-run before recording, or run live if time allows) | "This household's notes contain a hidden prompt injection telling the agent to approve and SMS every farmer. It was redacted before any model saw it. The draft is locked and cannot be signed." |
| 2:10 | Back to HH-DS-003: type a name, tick the box, **Sign & send** | "Nothing leaves without a named officer. The database itself refuses an unsigned approval." |
| 2:25 | **Sent messages** tab, then **Agent telemetry** with `approved_by` filled | "The SMS is queued, simulated. Every logged action of that run now carries the officer's name." |
| 2:40 | `EVALS.md` scrolled briefly | "Eight task types, five runs each on the local model, including one failure we have not fixed. Repo, licence and one-command setup are linked below." |

Upload as **public or unlisted-public on YouTube/Vimeo** and paste the link into the submission form and README.
