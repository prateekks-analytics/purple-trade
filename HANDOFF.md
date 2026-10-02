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

**Findings 3 Oct 2026 (later session, measured, no code changed):**
- GPU already in use: Ollama runs qwen3:8b on the RTX 4060 Laptop (8 GB), ~36 tok/s output,
  ~1,700 tok/s prompt. Time is almost all output generation, not prompt reading.
- Qwen3 "thinking" is ON in the TradingAgents run: Ollama generated 1,000–2,250 tokens per call while
  the saved visible answers are ~250–700 tokens → ~60% of the 593 s is hidden reasoning.
- Probe (same bear-analyst prompt, native `/api/chat`): think=on 30.5 s / 728 tokens; think=off
  5.2 s / 201 tokens, answer similar length. Quality impact on full decisions UNVERIFIED.
- Ollama context is 4,096 tokens (VRAM default); log shows 6 "context shift" events (half the
  prompt discarded) — TradingAgents prompts reach ~4,000 tokens. Raising num_ctx to 8,192 (~+0.6 GB
  KV) should fit in 8 GB; UNVERIFIED.
- Recommended order: (a) free — think off + num_ctx 8192 for TA runs (est. ~2–4 min/day), (b) market
  analyst only for backtests, (c) overnight precompute, (d) cloud only if quality is insufficient.
- Cloud cost estimate (Anthropic list prices cached 25 Sep 2026, per 1M tokens in/out: Haiku 4.5
  $1/$5, Sonnet 5.5 $2/$10, Opus 5.5 $4/$20; assumed ~50–80k input + ~8–12k output per trading day,
  2 analysts): Haiku ≈ $0.10–0.14/day, Sonnet 5.5 ≈ $0.20–0.30/day, Opus 5.5 ≈ $0.40–0.55/day.
  ESTIMATE — real token use not measured; needs API key + spend approval. TradingAgents ships an
  Anthropic client, so it is a config switch in `ta_runner.py`.

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
