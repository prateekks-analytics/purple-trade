# Purple Trade — new-chat handoff (3 October 2026, end of day)

Read this first, then `purple/README.md` (architecture, engine contract, SuperAgent, endpoints, commands).
Root `CLAUDE.md` section 1 describes the OLD root app — superseded; do not extend or reuse it.
Leave the TCS/Infosys RAG files untouched.

## What exists

- **Active build:** `purple/` — FastAPI + SQLite backend (`backend/purple_api/`), Vite + React + TS frontend.
- **Method 1 — your own ideas/files → rules.** Home idea box (text) and ONE button "⇪ Upload a file"
  (code .py/.pine/.js/.mq5…, .txt/.md, .csv, .xlsx, .docx, .pdf, .json). Purple JSON imports exactly;
  everything else is read as text (stdlib readers, best-effort PDF) and translated into rules by the AI.
  **Nothing uploaded is ever executed.** Then: inline-editable rules, auto-backtest, immutable versions.
- **Method 2 — Trading SuperAgent** (`#/super`, warp animation + dark layout). **Curated, pre-approved
  agents only; no upload.** Steps: Agent → Setup questions → Backtest → Paper trade → Deploy (Python file,
  DRY_RUN by default; optional Zerodha Kite hand-off, UNVERIFIED against current docs). Agents:
  1. **TradingAgents (original)** — real TradingAgents v0.5.2 (Tauric Research, Apache-2.0) in
     `purple/external/TradingAgents` (own `.venv`, git-ignored), run per day via `purple_api/ta_runner.py`
     on local Ollama qwen3:8b; API keys stripped; 45-min limit per day; prices/news from Yahoo Finance
     (`SYMBOL.NS`). Analysts selectable: market, news, social, fundamentals. Backtest ≤5 days.
  2. **TradingAgents Analyst Team** — Purple's faster rebuild (`agent_core.py`): deterministic market
     report → bull → bear → trader/risk, 3 AI calls per day (~20 s/day).
  3. Four rule bots from TradingAgents' indicator guide (Golden Cross, RSI 30/70, MACD Momentum, Fast EMA).
  4. CrewAI Stock Analysis — listed, "needs setup" (SEC filings + web search, no trades).
- **Featured bots** on the home page open SuperAgent with the agent preselected.

## Verified (3 Oct 2026)

- 53 backend tests pass (`cd purple\backend && .venv\Scripts\python.exe -m pytest -q`); `npx tsc -b` clean;
  `frontend/dist` rebuilt.
- Browser: warp → super layout; rule-bot backtests; rebuilt team 3-day backtest on live Qwen; paper
  account with next-day + team decisions; Deploy; 375 px phone width without horizontal scroll; single
  upload button; original agent card and its Setup (symbol + 4 analysts).
- **Real TradingAgents, CLI run:** RELIANCE.NS, 2026-10-01, market+news → **Buy** in **593 s**.
  Research manager and trader needed a free-text retry (8B model missed structured output); market
  report weak; news data reported unavailable; FRED macro skipped (no key). Thesis facts (Jio users, GDP
  growth) are model statements — UNVERIFIED.
- NOT verified: a full in-app run of TradingAgents (original) (bridge tested with a faked process only);
  dark mode / keyboard pass of normal mode; a real NSE-website CSV.

## Open topic for the next chat: TradingAgents speed

~10 min per trading day because one decision = ~15–25 LLM calls (2 analysts with tool calls, bull/bear,
research manager, trader, 3 risk debaters, portfolio manager) on local 8B at ~15–40 s per call; more
analysts = longer. Fine for one daily live/paper decision; painful for backtests (5 days ≈ 50 min).
Options to decide (user has not chosen):
1. Paid cloud model (est. 1–2 min/day; costs per run — quote cost and get approval first).
2. Faster machine / strong GPU (free, several times faster).
3. Fewer analysts (market only ≈ half the time, weaker analysis).
4. Pre-compute past days overnight in the background (decisions are already cached per day).

**Decision 3 Oct 2026 (user):** time (10–20 min/day) is acceptable; output quality matters; few runs at first →
use a better cloud model. Free options compared: Gemini free tier fits (Flash ~500–1,500 req/day reported);
Groq (8k tokens/min) and OpenRouter free (50 req/day) too tight. Limits are third-party reports — UNVERIFIED.

**Implemented 3 Oct 2026 (step 1, no paid calls made):** Setup question "Which AI runs the agents?" for
TradingAgents (original): Local Qwen (default) · Gemini Flash (free tier) · Gemini Pro managers + Flash analysts
(free tier; Pro preview may not be free) · Claude Opus 5.5 (paid; needs a ticked cost-approval box, est.
~$0.60–1.00/day, backend returns 402 without `confirm_paid`). Engine is available only when its key env var is
set (`GOOGLE_API_KEY` / `ANTHROPIC_API_KEY`) — user sets it, then restarts the API. Only the chosen engine's key
reaches the TradingAgents process; all other `*_API_KEY` still stripped. `ta_runner.py`: `--provider/--quick/
--deep/--effort`; cloud runs send no temperature, `max_tokens` 16000, 8 retries; Claude structured output forced to
native `json_schema` (Opus 5.5 rejects forced tool calls); per-day token usage counted and shown in decision notes.
Cloud decisions cached under their own key (local cache unchanged). 55 backend tests pass; tsc clean; dist
rebuilt; picker checked live on a temporary server (port 8781, `purple-api-check` in launch.json).
NOT verified: any real Gemini/Claude call (no key set); paper-trade "Ask" for TA still uses local only.
`GOOGLE_API_KEY` set by user (user env, setx); `purple-api` in launch.json now runs via PowerShell that copies
GOOGLE_/ANTHROPIC_API_KEY from the saved user env at start (values never printed). Restarted 3 Oct: local +
both Gemini engines available, Claude not (no key).
**First Gemini run 3 Oct (RELIANCE, 1 day, Flash, market+news): FAILED after 142 s** — Google 429: free tier for
`gemini-3.8-flash` is only **20 requests/day per model** on this key (resets ~midnight US Pacific); one TA day needs
more than 20 calls. Blog figures (500–1,500/day) were wrong for this model. Options: spread calls across models
(each has its own daily quota, e.g. flash-lite for analysts), enable Gemini billing, or use Claude/local.
**User plan:** 4 Oct try split Gemini (flash-lite analysts + Flash managers; not yet built); Anthropic key later.
Open idea (discussed, nothing built): improve small/low-context models via context discipline rather than CrewAI.
**Professor (3 Oct, via user):** use these agents/models as provided, at least initially → keep TradingAgents
(original) and CrewAI unmodified; small-model improvements only in Purple's own rebuild, later.
**UI declutter 3 Oct:** warp animation has no text (streaks + candles only); SuperAgent ticker tape removed, compact
header, agent picker split into "AI agents" / "Rule bots" (fits one 1366x800 screen, was 1206 px tall); Setup is a
two-column form + sticky Summary (stock, analyst chips, days, AI model dropdown, capital | agent, time, cost, Run),
fits one screen; Home 1839 → 864 px (short hero, upload button inside the idea box, short example chips, two
columns: strategies (first 6 + "Show all") and Featured agents list). Checked at 1366 px and 375 px (no sideways
scroll).
**Light SuperAgent + remaining panels 3 Oct:** SuperAgent no longer forces the dark neon theme — uses the site's
light theme (soft violet tint; follows OS dark mode like the rest). Backtest results (shared with the workspace)
show charts and the trade table as tabs in one card (Account value · Price & trades · Trades) → SuperAgent backtest
1208 → 845 px. Paper trade: one-line toolbar, logbook no longer repeats today's call ("Earlier days"). Deploy:
short intro, broker notes collapsed. Checked at 1366 px and 375 px, no console errors.
Progress label now names the chosen AI (was hard-coded "local AI, 30–60 s"). Next: one test day RELIANCE.NS 2026-10-01 (free Gemini first), compare
with Qwen's Buy. Claude.ai subscription can't be used for the API (separate pay-as-you-go Console billing).

## Other pending user decisions

- Full in-app TradingAgents run (~10–20 min) — ask before doing it.
- AI provider for the whole app (local Qwen vs paid); real NSE data source/licensing; FRED key (free).
- Optional PDF library (pypdf) for better PDF reading — install needs approval.

## Git

- `master`: 3fe281a initial · da3f726 new build · 5f289eb egg-info · 1b82b56 agent upload + SuperAgent ·
  a621e41 ignore purple/external · cba185a decision: curated SuperAgent · 8da0e0e single upload +
  original TradingAgents. This handoff rewrite is uncommitted unless committed after writing.
- No global git identity; commits use one-off `git -c user.name="Prateek" -c user.email="prateeksinghamu@gmail.com"`.
- Commit only when the user asks.

## Run

- One click: `purple\Start Purple Trade.cmd` → http://127.0.0.1:8780.
- Dev: `.claude/launch.json` → `purple-api` (8780; restart after backend edits) and `purple-web` (5173).
- Ollama qwen3:8b at 127.0.0.1:11434. DB `purple/backend/data/purple.sqlite3` (test paper account
  "TradingAgents Analyst Team · SAMPLE" exists). TradingAgents data/logs: `purple/external/ta_home/`.

## Working rules

- No uploads, mail, publishing, accounts, spending or installs without explicit approval.
- **Ask before redoing/repeating finished work** (re-runs, rebuilds, rewrites) — token cost.
- Never execute user-uploaded or AI-generated code. Only curated agents run.
- Verify live before claiming done; mark unverified claims; no subagents unless asked; terse replies.
