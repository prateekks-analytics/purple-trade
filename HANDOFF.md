# Purple Trade — new-chat handoff (3 October 2026, updated after Trading SuperAgent)

Read this first, then `purple/README.md` (architecture, engine contract, SuperAgent section, run/test
commands). Root `CLAUDE.md` section 1 describes the OLD app — superseded, do not extend or reuse it.

## Where things stand

- **Active build:** `purple/` — FastAPI + SQLite backend (`purple/backend/purple_api/`), Vite + React +
  TypeScript frontend (`purple/frontend/`).
- **Strategy workflow:** describe idea → AI proposal card → inline-editable typed rules → auto-backtest →
  immutable versions. Plus Upload an agent (code translated, never executed) and Download JSON.
- **Trading SuperAgent (new, 3 Oct):** separate mode with warp animation + full layout switch.
  Agent → Setup questions → Backtest → Paper trade → Deploy code. Featured: TradingAgents Analyst Team
  (Purple re-implementation of Tauric Research's workflow on local Qwen, market analyst only), four rule
  bots from TradingAgents' indicator guide, CrewAI Stock Analysis listed as "needs setup".
  Source: Prof. Ashok Harnal's mail of 27 Sep 2026 ("More Details — Project: Trade Algorithmically using
  AI agents") linking TauricResearch/TradingAgents and tonykipkemboi/crewAI-examples stock_analysis.
  Neither repo contains rule-based bots; nothing was downloaded or installed from them.
- **Tests:** 45 backend tests passing (31 earlier + 14 SuperAgent). `npx tsc -b` clean; `frontend/dist`
  rebuilt 3 Oct.
- **Browser-verified 3 Oct (built-in browser):** warp animation → super layout; RSI 30/70 and Golden
  Cross backtests; AI team 3-day backtest on live qwen3:8b (~50 s, HOLD ×3 with indicator-cited
  reasons); AI paper account → 2 × Next trading day → Ask the team (3 days: BUY then HOLD ×2, open
  position marked to market); Deploy code shown. Phone width 375 px: no horizontal scroll after a fix.
  Exported files run outside the app: rules script prints HOLD; AI team script runs the full debate and
  prints `[DRY RUN] would BUY 5 x SAMPLE`.
- Rule bots on the synthetic SAMPLE (750 days, B&H +61.56%): Golden Cross +0.87% (1 closed, 1 open),
  RSI 30/70 +16.99% (2 trades), MACD Momentum +14.84% (16), Fast EMA +1.43% (40). Synthetic, not market data.
- One paper account ("TradingAgents Analyst Team · SAMPLE") was created in the live DB during testing.

## Git

- Commits: `3fe281a` initial, `da3f726` new build, `5f289eb` untrack egg-info.
- **Uncommitted:** agent-upload feature (from 2 Oct) **and** Trading SuperAgent (new `agent_core.py`,
  `superagent.py`, `superagent_routes.py`, `tests/test_superagent.py`, `Warp.tsx`, `SuperAgent.tsx`;
  edits to `engine.py` (`trade_from`), `store.py`, `main.py` (routes + `/api/*` 404 instead of SPA HTML),
  `ai/providers.py` (seed 42), frontend `App/Home/Results/api/types/styles`), README, this file.
  Root `CLAUDE.md` also modified (not by this work). Ask before committing.
- No global git identity. Previous commits used one-off
  `git -c user.name="Prateek" -c user.email="prateeksinghamu@gmail.com"`.

## Run

- One click: `purple\Start Purple Trade.cmd` → http://127.0.0.1:8780.
- Dev: `.claude/launch.json` → `purple-api` (8780, restart after backend edits) and `purple-web` (5173).
- Local AI: Ollama `qwen3:8b` at 127.0.0.1:11434.
- DB: `purple/backend/data/purple.sqlite3` (new tables `agent_decisions`, `paper_accounts`).

## Known weaknesses (honest)

- Qwen 8B reasoning errors in the debate (e.g. bear called the lower Bollinger band "overbought"; mixed
  up SMA20/SMA200). The report numbers are deterministic; the model's interpretation is not reliable.
- Ollama output varied for the same day between runs (backtest HOLD vs paper BUY on 2025-11-14) before
  `seed: 42` was added; reproducibility after the seed is UNVERIFIED. Decisions are cached per run.
- AI team has only the market analyst; no news/fundamentals/sentiment (needs data sources + approval).
- Paper trading has no live feed: synthetic "next day" or newer imported CSVs only.
- Kite Connect call in exported code and broker/SEBI notes are UNVERIFIED against current docs.
- Earlier: narrow-screen pass only done for SuperAgent + home; dark-mode of normal mode, keyboard-only,
  real NSE CSV still not verified.

## Decisions waiting on the user

1. Commit (agent upload + SuperAgent).
2. Real TradingAgents: download + install it (separate venv) and/or add news/fundamentals sources.
3. AI provider: local Qwen vs paid model (no paid calls without approval).
4. Real NSE data source and licensing.

## Suggested next steps

1. Version comparison; dark-mode/keyboard pass of normal mode.
2. Paper trading on real NSE data (import CSV daily, or an approved feed).
3. If approved: news/fundamentals analysts, then a stronger model for the debate.

## Working rules carried over

- No uploads, mail, publishing, accounts, spending or installs without explicit approval; verify live
  before claiming done; mark unverified claims; no subagents unless asked; leave TCS/Infosys RAG untouched.
- Never execute uploaded or AI-generated code on the server. Exported code starts in DRY_RUN.
