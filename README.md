# Purple Trade — new build (started 2 October 2026)

Fresh implementation. The old root-level Purple Trade app (`purple_trade_*.py/js/html/css`, its docs and
`data/purple_trade/`) is **superseded and not used**: the user judged its output and workflow unusable.
Nothing here imports or copies it. The old files are left untouched on disk and in commit `3fe281a`.
Planning ideas carried over: NSE daily first, exact rule semantics, clarify instead of guessing, no
arbitrary code execution, immutable versions, every trade explained, research-only (no orders).

## The workflow (new)

One loop on one screen instead of the old multi-step pipeline:

1. **Describe** the idea (home screen) → AI drafts rules as a proposal card.
2. **Read exact rules** — the card and the rule editor are generated from the typed rule tree by code,
   never from AI text. Number/wording checks flag dropped numbers and "is above" read as "crosses".
3. **Apply / Discard** — the draft never changes until the user applies. Revisions show a +/− diff.
4. **Edit inline** — every indicator, period, operator, number, AND/OR group and NOT is a control.
   Flow diagram view is a read-only picture of the same tree.
5. **Auto-test** — every valid change auto-saves and re-runs the backtest (metrics, account-value vs
   buy & hold, price chart with ▲/▼ trades, trade table with the rule that fired).
6. **Upload an agent** (home screen) — users bring an existing bot. A Purple `.json` (from
   *Download JSON*) imports exactly. Source code (.py, .pine, .js, .ts, .mq4/.mq5, .txt, .md, .ipynb;
   ≤200 KB, ≤16k chars for the local AI) is translated by the AI into a proposal card, **never
   executed**; inexpressible parts (trailing stops, shorting, ML, broker calls…) become blocking
   "Not supported yet" questions. The original code stays visible above the rules, and a check flags
   fractions in the code (e.g. `0.05`) that no P&L rule uses. Endpoints: `POST /api/agents/import`,
   `GET /api/strategies/{id}/export`.
7. **Save version** — immutable snapshot. Blocked while open questions or errors exist, or when identical
   to the last version. Versions can be viewed read-only and used as a base for further edits.

## UI since 9 October 2026

Three sections: Test a bot, Build your own, Paper accounts (see HANDOFF.md "Redesign — done"). The SuperAgent
mode/warp described below was removed from the UI; its backend endpoints still serve Test a bot and Paper accounts.
Saved strategy versions can be used wherever an `agent_id` is accepted, as `version:<version id>`.

## Trading SuperAgent (added 3 October 2026; UI superseded 9 October)

Separate mode (`#/super`, topbar "⚡ Trading SuperAgent" or the home page's **Featured bots**). Entering
plays a full-screen warp animation (`Warp.tsx`, skipped with prefers-reduced-motion, click to skip) and
switches the whole site to a dark neon layout (`:root[data-mode="super"]`). Five steps:

1. **Agent.** Featured agents come from Prof. Harnal's 27 Sep 2026 mail (TradingAgents by Tauric Research;
   crewAI `stock_analysis`), plus "Upload your own bot" and "Your agents" (existing strategies).
   - *TradingAgents Analyst Team* (`agent_core.py`): Purple's re-implementation of the TradingAgents
     workflow, **not their code**. Market analyst report computed deterministically (SMA50/200, EMA10,
     MACD 12/26/9, RSI14, Bollinger 20/2, ATR14, VWMA20; bars up to the decision day only), then
     bull → bear → trader/risk manager on local Qwen (3 calls per day, ~15–20 s per day measured).
     Actions are validated (long only, one position; invalid → HOLD). News / fundamentals / sentiment
     analysts are shown but disabled until a data source is approved.
   - Four rule bots built from TradingAgents' indicator guide (`superagent.RULE_BOTS`): Golden Cross
     Trend, RSI 30/70 Reversal, MACD Momentum (EMA12 × EMA26 = MACD zero-cross), Fast EMA Momentum +
     Trend Filter.
   - *CrewAI Stock Analysis* is listed as "needs setup" (SEC filings + web search, US only, no trades).
2. **Setup.** Questions per agent: stock/dataset (or NSE CSV import), analyses, days to backtest
   (AI, 1–30), paper capital.
3. **Backtest.** Rule bots: the normal engine. AI team: background job (`/api/superagent/jobs/{id}`)
   with a live feed; same timing contract (decide on close, fill next open, 5 bps slippage, 3 bps fee).
   Decisions are cached in `agent_decisions` so the model is never re-asked for the same day.
4. **Paper trade.** `paper_accounts` start flat on the last day of the data. Synthetic accounts step
   forward with "Next trading day" (same seeded series, identical prefix); real-symbol accounts move when
   a newer CSV for that symbol is imported. AI accounts: "Ask the team" decides pending days; logbook kept.
5. **Deploy.** Standalone Python file (stdlib only): rule bots embed the exact rule tree + Purple's
   indicator code; the AI team embeds `agent_core` and calls local Ollama. `DRY_RUN = True` by default;
   optional Zerodha Kite Connect hand-off via env-var keys (call shape UNVERIFIED against current docs).

**TradingAgents (original)** (`kind: ta-original`): the real TradingAgents v0.5.2 in
`purple/external/TradingAgents` (own `.venv`, git-ignored) started by `ta_runner.py` per trading day on local
Ollama; prices/news from Yahoo Finance (`.NS`). ~10 min per day with 2 analysts (measured once).
SuperAgent runs only these curated agents; user files go through the single home-page upload (rules only).

Endpoints: `POST /api/superagent/paper/{id}/refresh`, `GET /api/superagent/agents`, `POST /api/superagent/run`, `GET /api/superagent/jobs/{id}`,
`GET|POST /api/superagent/paper`, `GET|DELETE /api/superagent/paper/{id}`, `POST .../next-day`,
`POST .../decide`, `GET /api/superagent/export?agent_id=&symbol=`.

## Run

- Double-click `purple\Start Purple Trade.cmd` → http://127.0.0.1:8780 (API + built UI on one port).
- Development (hot reload): `.claude/launch.json` configs `purple-api` (port 8780) and `purple-web`
  (Vite, port 5173, proxies `/api`).
- Tests: `cd purple\backend && .venv\Scripts\python.exe -m pytest -q` (57 passing on 9 Oct 2026).
- Type-check/build UI: `cd purple\frontend && npx tsc -b && npm run build`.

### First-time setup (new machine)

```
cd purple\backend
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[dev]
cd ..\frontend
npm install
npm run build
```

### Use Google Gemini (free) — recommended for a quick start

1. Get a free key at https://aistudio.google.com/apikey (Google account → "Create API key").
2. In the `purple` folder, copy `.env.example` to `.env` and paste the key after `GOOGLE_API_KEY=`.
   `.env` is ignored by git: **never put a real key in a committed file or on GitHub.**
3. Start Purple (`Start Purple Trade.cmd`). The AI that drafts rules switches to Gemini, and Test a bot picks
   "Google Gemini Flash (free tier)" for TradingAgents automatically.

Free-tier notes: requests are rate-limited (a "limit reached" message means wait a minute), and Google may use
free-tier prompts to improve its products — text you send to the AI goes to Google. Rule bots and backtests never
use the AI.

Alternative, fully offline: Ollama with `qwen3:8b` at 127.0.0.1:11434 (used when no Google key is set, or with
`PURPLE_AI_PROVIDER=ollama`). Without any AI, everything works except drafting rules from text.

The original TradingAgents (Test a bot → AI agents) also needs its own install in `external/TradingAgents`
(not included in this repository); without it, that option shows "Not installed" and the rule bots still work.

## Stack

- Backend `purple/backend/purple_api/` — FastAPI 0.142, Pydantic 2.13, stdlib SQLite, Python 3.12.
  (Package is `purple_api`, not `app`, because the RAG project's root `app.py` shadows `app`.)
  - `schema.py` typed rule tree (operands: price/indicator/const/position; conditions: compare,
    cross, all, any, not). `describe.py` plain-English + validation. `engine.py` backtest.
    `indicators.py` SMA/EMA/RSI(Wilder)/highest/lowest. `csvdata.py` NSE CSV import.
    `store.py` SQLite. `ai/` provider interface (Ollama now), prompt, parse/repair, checks.
  - DB: `purple/backend/data/purple.sqlite3` (override with `PURPLE_DB`). Not in git.
- Frontend `purple/frontend/` — Vite 8, React 19, TypeScript 6, @xyflow/react 12 (diagram).
  Charts are hand-built SVG (palette per dataviz guidance: strategy blue, buy & hold orange,
  status green/red markers with ▲/▼ glyphs).

## Engine contract

Signals on completed daily close; fills at next open with slippage; fee per side; long only; whole
shares; one position; `Days held` = completed bars since fill (fill day's close = 1); `Trade P&L %` vs
fill price; `=`/`≠` compare after rounding to 2 decimals (UI warns); open positions marked to last
close, not force-sold; no signal on the last bar can fill. Excludes STT, stamp duty, GST, exchange fees.

## Verified 2 Oct 2026

- 26 backend tests (hand-checked indicator values, next-open timing, exit reason reporting, equality
  rounding, no look-ahead, costs/whole shares, validation, CSV NSE export format, AI repair path, API
  flow incl. immutable versions).
- Live browser walkthrough (built-in browser, 1024 px): idea → proposal → apply → auto-backtest →
  inline edit re-tests → dismiss question → save version 1 → chat revision with diff → apply → save
  enabled for v2; diagram view; chart tooltip shows trade reason. No console errors.
- Live local Qwen3:8b on user's examples: RSI "is 10 / above 90" → `RSI(14) = 10`, `RSI(14) > 90`
  plus period/equality questions; SMA20 dip → exact cross + 2-day/±1% ANY exit; EMA cross OK;
  options short → refused as "Not supported yet". Known weaknesses: it still writes "crosses" for
  "is above" (flagged by the wording check, one-click fix), and produced a meaningless rule for
  "sell at next day's close" (accompanied by a blocking question). ~12–25 s per request.
- NOT verified: mobile/narrow layout rendering, dark mode rendering, real NSE CSV from the NSE site
  (format covered only by a test fixture), keyboard-only pass.

### Agent upload, verified 2 Oct 2026

Browser test with a Pine Script EMA-crossover bot (EMA20/50 cross, RSI<60, 5% TP, 2% SL, crossunder exit,
3% trailing stop): Qwen translated the entry, SL and crossunder exactly, flagged the trailing stop as
unsupported, but misread the TP as 3%. The percentage check flagged "0.05 (= 5%) not used"; after an
inline fix the backtest ran. Lesson: code translation by the 8B model needs the side-by-side source
and checks; a stronger model would reduce misreads.

## Decisions pending (user)

1. **AI provider.** Local Qwen is free but makes mistakes the safeguards must catch. Options discussed:
   Claude Sonnet 5.5 via API (~$0.02–0.04 per idea, estimated; billed to API credits, not a Claude
   subscription), Gemini Flash / Groq / OpenRouter free tiers (rate-limited; data terms UNVERIFIED).
   `purple_api/ai/providers.py` is the single place to add one. No paid calls without approval.
2. Real NSE data source/licensing (currently: user-imported CSVs + clearly labelled synthetic sample).

## Next steps

1. Narrow-screen + dark-mode visual pass; keyboard pass.
2. Import a real NSE CSV export and sanity-check results by hand.
3. Version comparison (side-by-side metrics of v1 vs v2 on the same data).
4. Paper-trading replay and downloadable runnable package (planned journey steps 6–7).
5. More operands only when needed (e.g. % change over N days, ATR) — keep exact semantics.
