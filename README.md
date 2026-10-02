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
6. **Save version** — immutable snapshot. Blocked while open questions or errors exist, or when identical
   to the last version. Versions can be viewed read-only and used as a base for further edits.

## Run

- Double-click `purple\Start Purple Trade.cmd` → http://127.0.0.1:8780 (API + built UI on one port).
- Development (hot reload): `.claude/launch.json` configs `purple-api` (port 8780) and `purple-web`
  (Vite, port 5173, proxies `/api`).
- Tests: `cd purple\backend && .venv\Scripts\python.exe -m pytest -q` (26 passing on 2 Oct 2026).
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

Optional AI: Ollama with `qwen3:8b` at 127.0.0.1:11434. Without it, everything works except chat drafting.

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
