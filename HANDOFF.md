# Purple Trade — new-chat handoff (updated 15 October 2026, evening: live data + news agents)

**START HERE: section "Current state (15 Oct 2026)" is authoritative. Everything below it is history.**

Read this first, then `purple/README.md`. Root `CLAUDE.md` section 1 describes the OLD root app — superseded; do not
extend or reuse it. Leave the TCS/Infosys RAG files untouched (they share the CIS repo).

## Current state (15 Oct 2026; Beat the market added 22 Oct)

**Purple Desk online: Render + Hugging Face dataset backup (22 Oct 2026, morning after)**
- LIVE since 22 Oct ~10:12 IST: https://purple-desk-qgjw.onrender.com (Render service srv-dbcp75lg1s2s73e2jk70,
  Blueprint purple-desk, commit 748ff42). Password = PURPLE_PASSWORD (user typed it; any user name). The laptop
  server was stopped at 10:10 after a fresh DB upload; do NOT start `purple-api` on 8780 with the live loop again
  while the online bot runs (two bots). `purple/coach/hub.txt` = the state dataset, so `/coach-bot` works online.
- Keep-awake: the server pings its own RENDER_EXTERNAL_URL every 10 min (only when sync is on). GitHub workflow
  version parked at `deploy/keep-awake.yml` (gh token lacks `workflow` scope).
- 22 Oct 09:40 IST the laptop server (8780) was down (lid closed); restarted via preview `purple-api`; Gemini decided
  09:15. Local DB bot f87d385cea46 (open-ended, started 21 Oct 15:30).
- HF Docker Spaces now need PRO (402 on create; nothing paid). Hosting = a second Render free web service
  `purple-desk` (blueprint `render.yaml`: `deploy/Dockerfile`, Singapore, health `/api/health`, env GOOGLE_API_KEY,
  HF_TOKEN, PURPLE_PASSWORD typed in Render; PURPLE_STATE_REPO=Prat8118/purple-desk-state, PURPLE_STATE_SYNC=1).
  The public demo purple-trade.onrender.com (root Dockerfile, PURPLE_HOSTED) is unchanged.
- State: private HF dataset `Prat8118/purple-desk-state` (created 22 Oct, holds a snapshot of the laptop DB with
  the running bot + playbook). `purple_api/hfsync.py` restores DB + playbook at startup, backs up the DB every 10
  min if changed and on shutdown, syncs the playbook 3-way (hub wins). Failed restore → backups off that run. Only
  on when SPACE_ID or PURPLE_STATE_SYNC=1 (never the laptop). `/api/health` shows `state_backup`.
- `PURPLE_PASSWORD`: HTTP Basic gate on everything except `/api/health` (any user name).
- Awake: `.github/workflows/keep-awake.yml` (in the public repo) pings `/api/health` every 10 min 08:30-16:30 IST
  weekdays (`vars.DESK_URL`, default https://purple-desk.onrender.com).
- Reviews and the journal are git-ignored (the purple/ subtree is public). `/coach-bot` hosted mode starts when
  `purple/coach/hub.txt` names the dataset (write it at switch-over); uses the CIS `.venv` `hf` CLI (user logged in
  as Prat8118 on 22 Oct).
- Switch-over: stop the laptop server, upload a fresh DB snapshot to the dataset, restart the Render service, check
  the bot decides there. Yahoo/Google News from Render: UNVERIFIED. Docker image not built locally (Docker off).

**Claude coaches the bot (22 Oct 2026, evening; not pushed)**
- Goal: after each trading day Claude Code reviews the desk's decisions and writes a short playbook; the Gemini chief
  reads it in every decision. Claude never runs in the live loop; no paid calls. Not scheduled yet (user can ask).
- `purple_api/coach.py`: review pack (`build_review`: day summary desk vs NIFTY, winners, trades; per decision
  "knew" = NIFTY state, mood read at or before the bar, each agent's proposal + two-day record + debate case, coach
  rules shown; "chose" = winner, targets, reason, confidence, by, rules_used; "outcome" = hindsight returns from the
  bar's close over 1/3/13 bars for desk, NIFTY and each agent's shadow portfolio, None when not yet known),
  `write_review` → `purple/coach/reviews/<day>.md` + `.json`, playbook parse/render/retire/check, `scorecard`
  (per rule: 3-bar edge vs NIFTY of AI decisions that cited it vs those that saw it and did not; verdict "too early"
  until followed ≥4 times on ≥2 days, then helping / hurting / no clear effect at ±0.05 pts). Also now holds the
  shared `load_panel`, `run_book`, `mood_index` (desk_routes calls them). CLI: `python -m purple_api.coach review
  [--day] [--bot]` and `check`. `PURPLE_COACH_DIR` overrides the folder (tests, scratch server).
- Playbook format: `## R<n> | active|trial|retired | added <date>[ | retired <date>]`, then `Rule:` and `Why:`.
  Live = active + trial, max 10. `desk.chief_prompt(..., rules)` appends them in one `<data>Coach playbook: ...</data>`
  line (text cut at 160 chars); `CHIEF_SYSTEM` calls it advice that never changes the limits and asks for
  `rules_used`; `parse_chief(raw, props, rule_ids)` keeps only shown ids. Decisions store `rules_shown`/`rules_used`.
- Routes: `GET /api/desk/review?day=&save=`, `POST /api/desk/coach/rules/{id}/retire`; `GET /api/desk` has
  `coach.rules[]` with scores and decisions carry `rules_used`. UI: "Coach notes" panel in `BotBrain.tsx` (rules, date,
  why, verdict chip, followed count + edge, Remove with confirm); debate note says which rules were followed.
- `/coach-bot` = `CIS/.claude/commands/coach-bot.md` (review → judge on what it knew → edit playbook → `coach check` →
  journal entry → commit `purple/coach/` locally). Playbook starts empty (no evidence yet).
- `purple-desk-test` now also sets `PURPLE_COACH_DIR=%TEMP%\purple-desk-test-coach` (seeded test rules there).
- Verified: 100 backend tests (5 new in `tests/test_desk.py`), tsc + build clean, on the scratch server: review
  endpoint, Coach notes panel, Remove (playbook marked retired), 375 px no sideways scroll. NOT yet seen: a real
  Gemini decision citing a rule, and a `/coach-bot` run on a full real trading day. The user's server on 8780 runs
  the old code until restarted; after a restart the bot reads `purple/coach/playbook.md` at every decision.

**Purple Desk: the main product (22 Oct 2026, later the same day; not pushed)**
- User brief: home = one AI trading bot. Start with an amount (default ₹5,00,000), it paper-trades on its own every
  30 minutes (buy/sell/hold), for 7 days, 30 days or until stopped; dashboard like a trading app (portfolio vs NIFTY,
  what it bought and sold, holdings). Agents debate, the winner's plan trades, the bot learns from news, social and
  results. Old single-stock tools out of sight. Look: light, clean, futuristic accents. User picked "AI every 30 min".
- Universe: 10 large NSE stocks (`desk.UNIVERSE`), long only, whole shares, fees 3 bps + slippage 5 bps per side,
  max 35% per stock, rebalances under 4% skipped. 30-minute Yahoo bars (`market_bars`, interval '30m').
- `purple_api/desk.py`: five strategist agents in code (Momentum, Trend rider, Dip buyer, News & social, Risk guard)
  each propose target weights per bar; every agent runs a shadow portfolio = its track record. AI chief
  (`CHIEF_SYSTEM`, 1 call per bar) hears all cases + two-day records + news mood + lessons, returns debate, winner,
  targets, plain reason; `parse_chief` validates (unknown symbols dropped, caps). No AI → `judge` picks the best
  two-day record. Mood: 1 AI call every 2 h over Google News + Reddit headlines (`MOOD_SYSTEM`). Lessons: 1 AI call
  after the close (`LESSON_SYSTEM`), fed to the chief. About 18 AI calls per trading day.
- `purple_api/desk_routes.py`: `GET/POST /api/desk`, `POST /api/desk/stop`, `POST /api/desk/decide`,
  `GET /api/desk/backtest?days=40&capital=`. `app.state.desk_tick` runs in the main live loop (60 s; decides the newest
  completed bar once, skips missed older bars, 09:45-16:15 IST weekdays). Table `desk_bots`; decisions, moods and
  lessons in `agent_decisions` under `desk:`, `deskmood:`, `desklesson:` + bot id. Only downloads hold the lock (an
  earlier version froze the dashboard while the AI debated).
- Backtest (no AI, judge by record), real data to 21 Oct: 40 days bot −0.96% vs NIFTY −6.02% (+₹25,285 on ₹5 lakh,
  4 of 5 weeks ahead); 55 days −2.95% vs −7.11%, ahead in both halves. Most of the edge came from cash and dip-buying
  in a falling market; Momentum and Trend lost money in this period. Tuned only the judge window (2 days kept).
- Gemini: 429 now also falls through to the next model (each has its own free quota; skipped 120 s). Live chief
  call verified (13 s, full five-agent debate). Earlier the same day the newest models hung or hit the daily limit.
- Frontend: nav = Dashboard `#/` (`Dashboard.tsx`: launch with amount/duration + replay proof; running: value, vs
  NIFTY, status, performance chart with trade markers, latest decision, holdings with live quotes, trades), Bot `#/bot`
  (`BotBrain.tsx`: agent cards, debates, mood, lessons, backtest), More `#/more` (`More.tsx`: Ask the agent, Test/Build
  a rule bot, Beat the market, Paper accounts, classic home `#/classic`). Default theme light. Header wallet removed.
- Verified: 95 tests pass; tsc + build clean; launch → start → first decision on a scratch DB (`purple-desk-test`,
  port 8782, `%TEMP%\purple-desk-test.sqlite3`, live loop on); 375 px no sideways scroll. NOT yet seen: trades and
  chart markers during market hours, the lessons call, a full 7-day run. The user's real DB has no desk bot yet.
- Claude (22 Oct): user's key is in `purple/.env` (git-ignored) and valid for claude-opus-5-5, but the API account has
  no credit (credit-balance error on a tiny call; nothing charged). Pro-plan "cloud session credits" ($100, expire
  5 Nov) do not pay for API calls. User chose: keep the bot on free Gemini; Claude later. Re-check with
  `backend\.venv\Scripts\python.exe tools\claude_check.py` (anthropic SDK 2.1 installed with approval). Wiring the desk
  to Claude Opus 5.5 with Gemini fallback is NOT built yet; `default_provider` ignores ANTHROPIC_API_KEY.
- To run it for real the server must stay up during market hours with the live loop on (`purple-api` config, port
  8780, or the exe after a rebuild); `purple-check` has the loop off.

**Beat the market: single-stock (22 Oct 2026, commits after f359792; now under More)**
- User brief: main objective is to backtest a bot, improve it with AI agents, and show a bot that stays ahead of the
  market for a 7-day period, then prove it with a real-time paper race for a week. Fewer numbers, more plain benefit.
- New page `#/race` (`components/Challenge.tsx`), first nav item ("Main goal") and a banner at the top of Home.
  Steps: pick a rule bot + stock → replay → AI coach → "Start the 7-day race" → race page `#/race/<paper id>`.
- Backend `purple_api/challenge.py` + routes in `superagent_routes.py`:
  `POST /api/challenge/replay {agent_id|strategy, symbol, weeks}`: last 24 non-overlapping weeks of WEEK=7 sessions,
  each starting flat with ₹1,00,000 at a close (warm-up from earlier bars); market = NIFTY 50 (`^NSEI`) between the same
  two closes. Summary: weeks beaten, average weekly ₹ edge, `cash_beat` (weeks NIFTY fell, which plain cash also wins),
  idle weeks, verdict. Verdict checks idle/cash first, so a bot that never buys can't look "strong".
  `POST /api/challenge/coach` (job, 3 AI calls): AI proposes a change via `ai.propose`, code replays, the next try sees
  earlier tries; keeps the best by (weeks beaten, avg edge) on the older 16 weeks only; the newest 8 (HOLDOUT) are the
  unseen check shown to the user. `POST /api/challenge/keep` saves an improved bot as strategy + version 1.
  `POST/GET /api/challenge/races[/{id}?live=1]`: a race is a daily paper account with `race_days`=7 (new column, store
  migration). The view caps at 7 sessions, NIFTY normalised to the same capital, live mark-to-market with Yahoo quotes
  while NSE is open; prices re-downloaded at most every 10 min per symbol. Rule bots only (AI agents: 1 call per day).
- Gemini fix: `GeminiProvider` timeout 120 → 45 s, a timed-out model is skipped (next fallback) and remembered for
  10 min (`_HUNG`). On 22 Oct gemini-3.8-flash and 3.7-flash hung (even "Say OK"); 3.5-flash answered in ~6 s.
- Real data (RELIANCE, 24 weeks to 21 Oct): every built-in bot sat in cash most weeks (Golden Cross never bought; Fast
  EMA idle 19/24) and "won" mainly because NIFTY fell; plain cash would have won 16 weeks. The coach turned Fast EMA 10
  into EMA 5: 15 → 16 of 24, unseen weeks 5 → 5. So no bot is clearly ahead yet; this is the honest starting point.
- Live race started 22 Oct 06:30 IST from the UI: "Fast EMA Momentum + Trend Filter (AI coached)" on RELIANCE, start
  close 21 Oct, id a09b96537d8f (strategy saved as version 1). Day 1 = 22 Oct session.
- Verified: 87 backend tests pass (`tests/test_challenge.py` + Gemini hang test), tsc + build clean, replay + coach +
  keep + race clicked live on purple-check (8781, real Gemini); no sideways scroll at 375 px; tab bar now 6 columns.
  NOT yet seen: a race with day ≥ 1 and the live (session-open) mark-to-market path; check after 09:15 IST.

**Kite / Alpaca-style shell (16 Oct, early; frontend only; previous UI commit 140d63b)**
- User benchmark: Zerodha Kite and Alpaca; wanted a hover-to-open sidebar instead of a fixed one.
- Sidebar is a 72 px icon rail that opens over the page on hover or keyboard focus (content never shifts).
- Top bar: live NIFTY 50 / SENSEX (`^NSEI`, `^BSESN`), Kite-style search box, paper money, NSE status, AI dot.
- Ctrl+K or `/` opens `components/Palette.tsx`: type a stock → "Should I buy X?" (→ `#/agent/X`) or add it to the
  watchlist; jump to pages, rule bots, paper accounts; switch theme; connect AI.
- Home: `components/Watchlist.tsx` (localStorage `purple.watchlist`, default 8 NSE stocks; hover shows Ask / remove;
  becomes a swipe row under 1100 px), greeting, hero, "Get started" checklist (AI connected, first agent call,
  first backtest, a paper account; flags `purple.done.*`, hideable).
- `lib/quotes.ts`: shared quote cache (60 s TTL, polls every 2 min, first load even in a hidden tab) = 10 Yahoo
  calls per page load with the default list. TATAMOTORS has no Yahoo quote since the demerger (replaced by LT).

**Consumer UI redesign (15 Oct, night; frontend only; restore point 65ee27b)**
- User brief: less text, more inviting, "real paid app" feel; purple only as subtle streaks, not everywhere.
- Look: neutral canvas (light #f4f5f7 / dark #0b0c0e), ink-black buttons, purple as streaks only (`--streak`
  gradient: active nav bar, stock-name underline, soft hero light band, rank-1 / selected card edge, chart lines).
  Saffron #ffb547 tiny highlights. Fonts: Bricolage Grotesque (display, numbers) + Plus Jakarta Sans (body).
- New `components/Desk.tsx`: `AskSentence` ("Should I buy RELIANCE?" with the symbol as an inline field),
  `DeskRow` (six analyst faces that light up from the real job log), `botLook`/`BotBadge` (icon + colour per bot).
- Home: hero question → `#/agent/<SYMBOL>` (prefills, does not auto-run), three picture cards, paper money,
  podium of top-3 rule bots. Agent: hero ask bar, call card with big word, confidence ring, stop/close/target
  ladder, two next-step cards, research desk (steps collapsed). Test/Paper: bot/account card rail on top.
  Build: hero composer, template cards, your-bots cards. Phones: bottom tab bar, compact top bar.
- Verified: tsc + build clean, 81 tests pass, 1366 px and 375 px (no sideways scroll), light + dark, no console
  errors; one real call on free Gemini (TCS → Wait, 65%) rendered the call card.

**Agent vs bot split (15 Oct, late; commits cd07db6, a7bb2c8, ecf6461; not pushed)**
- Wording everywhere: **AI agent** = an AI that researches a stock and makes a call; **rule bot** = fixed indicator
  rules, no AI. Sidebar groups: Overview · AI agent (Ask the agent `#/agent`) · Rule bots (Test a bot `#/test`, Build a
  bot `#/build`) · Practice (Paper accounts). Overview opens with a three-card "start here" row.
- **Purple Research Agent** (`purple-agent`, kind `ai-agent`, `live_agents.agent_decider`): market analyst (code) →
  news & trader-posts analyst (1 AI call) → fundamentals analyst (1) → bull (1) → bear (1) → risk manager (1) gives
  action + plain view + confidence + "what would prove it wrong"; stop-loss/target = close ∓ 2×/3× ATR (code). Analysts
  can be switched off (fewer calls). Daily paper accounts only; the live loop decides them with the server's free AI.
- `POST /api/agent/call {agent_id, symbol, analyses, holding, fresh}` → job with one call on the latest completed
  session (+ live delayed quote in the report while the session runs); cached per agent/AI/analysts/dataset/position.
  Works for `tradingagents-original` too (Agent page radio "Original TradingAgents").
- Agent page: ask panel (stock, own it?, checks, agent) → six-step pipeline filling live → call card (Buy / Wait /
  Avoid / Hold / Sell from the person's point of view) → What next: start a paper account, or check the last 3/5/10 days.
- Hidden from the UI but still runnable (old accounts, tests): News & Social Pulse, Stock Analysis Crew, Analyst Team
  (`hidden: true` in the catalog). Test a rule bot no longer contains any AI-agent code.
- Verified 15 Oct: 81 tests pass; tsc clean; dist rebuilt; real call on free Gemini: RELIANCE → "Wait" (view HOLD, 70%),
  all six steps filled, ~1.5 min. Checked at 1366 px and 375 px (no sideways scroll). Paper-account creation from the
  Agent page and the past-days check were NOT clicked live (backend tests cover them).
- `.claude/launch.json` has `purple-check` (port 8781, serves built `frontend/dist`, live loop off) because another
  chat's `purple-api`/`purple-web` held 8780/5173. Restart `purple-api` before using the new endpoint on 8780.


**Live and shared**
- Web demo: https://purple-trade.onrender.com (Render free plan, auto-deploys on push to GitHub `main`; sleeps when
  idle, ~1 min wake, data wiped on restart; shared-demo banner shown via `PURPLE_HOSTED=1` in `Dockerfile`).
- Public repo: https://github.com/prateekks-analytics/purple-trade — contains ONLY `purple/`. Publish with:
  `git subtree split --prefix=purple -b purple-public` then `git push https://github.com/prateekks-analytics/purple-trade.git purple-public:main`.
  Scan for keys before every push. Commit author email (prateeksinghamu@gmail.com) is public in history.
- Windows app: release v1.1.0, stable link
  https://github.com/prateekks-analytics/purple-trade/releases/latest/download/PurpleTrade-windows.zip
  (`build_exe.ps1` → `dist_exe/PurpleTrade.exe`; PyInstaller in backend/.venv; zip staged in
  `C:\Users\prate\Claude\purple-trade-release\`). v1.1.0 lacks only the tiny padding fix 43c5152.
- User approved pushing and releasing for this project (12 Oct). Auto-commit is on (local); push only when asked.

**UI (trading-desk redesign, commits ff4c7f5 → 43c5152)**
- Shell: deep purple sidebar (Overview, Test a bot, Build your own, Paper accounts), top account bar (paper equity,
  total P&L, accounts, NSE open/closed by IST clock, holidays not checked), light/dark toggle (`purple.theme`).
  Fonts: Plus Jakarta Sans + IBM Plex Mono (axes only). Purple must remain the brand colour (user, 10 Oct).
- Overview (`#/`): combined paper-equity chart, accounts with sparklines, rule-bot leaderboard (never-traded last).
- Test a bot (`#/test[/<botId>]`): bot list | candlestick chart + verdict | "Backtest ticket" with run and
  "Start paper account". Saved strategies run as `version:<vid>`.
- Paper accounts (`#/paper[/<id>]`): account list | account bar + chart + logbook | "Today" call and Next day.
- Charts: `components/Charts.tsx` (CandleChart with volume/OHLC/markers, RangeTabs, Spark), `LineChart.tsx` (area).
  Palette validated: light #5b3fe0/#e8692e, dark #8c78ff/#e0702f.
- Verdict text (`lib/verdict.ts`) is computed from numbers only.

**AI (in-app keys)**
- "Connect an AI" dialog (`components/AiConnect.tsx`): Gemini, Groq, OpenRouter, OpenAI, Anthropic, Ollama (hidden
  when hosted). Key stays in the browser (`purple.ai` localStorage) and is sent as X-AI-Provider/Model/Key headers per
  request; server never stores it. Asked once per session when no AI is available.
- Backend: `ai/providers.py` (GeminiProvider with retry + fallback chain, OpenAICompatProvider, AnthropicProvider,
  `make_provider`, `CATALOG`), `/api/ai/providers`, `/api/ai/test` (lists models, no cost). Browser keys also reach
  TradingAgents runs. Local `.env` (git-ignored) still supported; `.env.example` documents it.
- Free-tier Gemini is often overloaded (503); the fallback handles most cases.

**Backend changes since 9 Oct**: saved versions as rule bots (15e564f); SQLite race fix (6b61d78); Gemini + multi-
provider (e7f17fd); `launcher.py` + `PURPLE_DIST` for the exe; hosted flag in `/api/health`. Tests: **62 passing**
(`cd purple\backend && .venv\Scripts\python.exe -m pytest -q`).

**Dev**: `.claude/launch.json` → `purple-api` (8780) + `purple-web` (5173, open http://localhost:5173). Restart the
API after backend edits. Visual checks used headless Edge over CDP (`shot.mjs` lived in the session scratchpad, not
the repo) because the in-app browser pane does not render while the window is minimised.

**Live market data (15 Oct, committed locally; not pushed yet)**
- `purple_api/market.py`: Yahoo Finance public chart endpoint via httpx (no key, no new package). Completed daily
  sessions only (today's bar counts after 16:00 IST; Yahoo's blank newest close is filled from `regularMarketPrice`).
  Quotes ~15 min delayed; unofficial, not verified against NSE.
- Endpoints: `POST /api/market/prices {symbol}` (stores a dataset, deduplicated by hash), `GET /api/market/quote`.
  Paper accounts created with a `symbol` (any bot kind) start at the latest session; `refresh` uses Yahoo, no
  TradingAgents install needed. `ta_prices` removed; TA tests now mock `market.daily_bars`. Tests: **67 passing**.
- UI: price picker "Add a stock" → "Get live prices"; Test a bot passes the symbol for Yahoo datasets; Paper page shows
  a live quote panel (polls every 60 s, pauses when the tab is hidden), "Value now", and auto-refreshes the account
  once a newer session has closed. Daily rules still decide on the close and fill at the next open.
- Local test accounts left in the DB: "Golden Cross Trend · INFY.NS" (daily) and "Golden Cross Trend · INFY.NS · 5m".
  Hosted demo reaching Yahoo from Render: UNVERIFIED until pushed.

**Intraday paper trading + news agents (15 Oct, commits edb2f3b and the frontend commit after it; not pushed)**
- Paper accounts have an `interval` ('1d', '5m', '15m', '30m'; column added by migration). Intraday bars live in the
  `market_bars` table (upserted, completed bars only, 'YYYY-MM-DD HH:MM' IST). Rule bots: 1d/5m/15m/30m; News Pulse:
  1d/15m/30m; Crew: 1d/30m; TradingAgents and the hidden team: daily only.
- Live loop (`main.py` lifespan thread, every 60 s; `PURPLE_LIVE_LOOP=0` disables; tests call `app.state.live_tick`):
  fetches intraday bars 09:15–15:45 IST Mon–Fri, the daily close after 16:00 IST, and lets the SERVER's own free AI
  (gemini/ollama only, never a browser key) decide pending bars of news agents. Exchange holidays not checked.
- Yahoo rate limits: a 429 pauses all Yahoo calls 60 s; `GET /api/market/status` reports it plus loop errors; the
  Paper page shows a warning. `market.FEEDS` lists Yahoo and a not-connected broker slot (Upstox/Angel One/Kite,
  user's own key, pricing UNVERIFIED) for later.
- `news.py`: Google News RSS (date-filtered for past days), Reddit RSS search (r/IndianStreetBets + r/IndianStockMarket;
  JSON API returns 403; RSS sometimes 429), Yahoo headline RSS (nearly empty for NSE). StockTwits API returned 403.
  Items are filtered by publish time ≤ decision bar (no look-ahead) and treated as data in prompts.
- `live_agents.py`: News & Social Pulse (`news-pulse`, kind ai-news, 1 AI call/decision) and Stock Analysis Crew (NSE)
  (`crew-nse`, kind ai-crew; Purple's re-implementation of Prof. Harnal's crewAI stock_analysis link: research →
  financial (Yahoo annual figures, 60-day filing lag) → advisor; 3 calls). They use the browser's connected AI, else
  the server default. Verified live 15 Oct on Gemini: Pulse read 25 RELIANCE items → BUY with cited items; Crew on
  INFY → HOLD (Reddit 429 noted, run continued). No code export for these two (400).
- Paper page: "Bars followed", intraday labels, opt-in "decide new bars automatically" (localStorage per account).
- Tests: **76 passing** (`tests/test_live.py` added; two catalog tests updated because the crew is now runnable).

**Not done / open**
- NOT PUSHED: commits 3662d46, edb2f3b, e774f9d (live prices, intraday, news agents) are local only. Push when the
  user asks (subtree split, see top); then check Render can reach Yahoo/Google News/Reddit (UNVERIFIED).
- Intraday bar-by-bar movement not yet seen live (built while NSE was closed): check during 09:15–15:30 IST that the
  5m account advances and `/api/market/status` shows `bars_saved` rising and no errors.
- Exe (v1.1.0) predates all of the above; rebuild/release only when the user asks.
- Live-trading idea parked: real-time broker feed (Upstox / Angel One / Kite) needs the user's own account + key.
- Full TradingAgents run through the new UI (~10–20 min; ask first). TradingAgents is not in the exe or the web demo.
- Docker image never built locally (Docker Desktop off); Render build succeeded, which is the real check.
- Screen-reader (NVDA) test, 200% zoom check.
- Test data in the local DB: paper account "MACD Momentum · SAMPLE"; strategies "Gemini check: RSI 30/70",
  "Header check: EMA cross" (x2).
- Ideas not started: candlesticks for real-symbol paper accounts, per-visitor workspaces on the hosted demo,
  code-signing the exe (SmartScreen warning).

---

## History (pre-15 Oct)

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

## Sharing (9 Oct 2026)

- Public repo: https://github.com/prateekks-analytics/purple-trade (only `purple/`, pushed with
  `git subtree split --prefix=purple -b purple-public` then `git push <repo> purple-public:main`).
- Windows app: release v1.0.0, stable link
  https://github.com/prateekks-analytics/purple-trade/releases/latest/download/PurpleTrade-windows.zip
  (rebuild with `build_exe.ps1`; PyInstaller is installed in backend/.venv). Data: %LOCALAPPDATA%\PurpleTrade.
- "Connect an AI" dialog: Gemini, Groq, OpenRouter, OpenAI, Anthropic, Ollama. Key kept in the browser and sent
  as X-AI-* headers per request; server never stores it. Gemini retries + falls back when the free tier is busy.
- Hosted demo: `Dockerfile` (PURPLE_HOSTED=1 shows a shared-demo banner). Docker build NOT verified (Docker
  Desktop was not running); hosted settings verified by running uvicorn with the same environment.
  Needs the user to create a free Render or Hugging Face account.
- Tests: 62 passing.

## Redesign — done (9 Oct 2026)

One app, three sections in the top bar (hash routes): **Test a bot** `#/test[/<botId>]`, **Build your own** `#/build`
(rule workspace `#/s/<id>`), **Paper accounts** `#/paper[/<id>]`. SuperAgent mode, warp, Analyst Team rebuild and
CrewAI card are hidden (backend catalog unchanged; rebuild's paper accounts kept in DB, filtered from the list).
Deploy is a small "Download code" link.
- Test a bot = 4 numbered steps: choose (TradingAgents original / 4 rule bots / saved versions as `version:<vid>`)
  → set up (price data or NSE symbol, analysts, days, AI model, stated assumptions) → run (time/cost estimate;
  confirm dialog before TradingAgents runs) → verdict → "Start paper account" + Download code.
- Verdict (`frontend/src/lib/verdict.ts`) is computed from the numbers only: beat/trailed/matched buy and hold or
  "never traded", money sentence, 4 facts (return, worst fall from a peak vs holding, trades, time invested), and
  "What this means" caveats (few trades, <1 year, losing-but-beating, worse on both counts, synthetic data).
- Look: IBM Plex Sans + Newsreader (Google Fonts link in `index.html`; falls back offline), violet ink on cool paper,
  light + dark tokens in `styles.css` (clean rewrite). Chart pair #4a3aa7/#eb6834 (dark #9085e9/#d95926) passed the
  dataviz validator. Contrast checked (text ≥5:1; field borders 3.5:1+). Charts keyboard-readable (arrows).
- Reviews run: design-critique, accessibility-review, ux-copy; fixes in 3ccc277.
- Backend: saved versions run as rule bots (`agent_id=version:<vid>`, 15e564f); SQLite race fixed (rows fetched
  inside the lock, 6b61d78). Tests: **57 passing**. Production UI rebuilt (`npm run build`) for the one-click launcher.
- Screenshots: the in-app Browser pane could not render while the window was minimised; verified with headless
  Edge over CDP (script was in the session scratchpad, not the repo).
- Test data created during verification: paper account "MACD Momentum · SAMPLE" (synthetic, advanced 3 days).
  Not deleted; delete it in Paper accounts if unwanted.
- Not done: full TradingAgents run through the new UI (needs your OK, ~10–20 min); NVDA/VoiceOver test; 200% zoom.

## Redesign decision (9 Oct 2026, user)

UI judged "too tacky to show the professor"; use cases "haphazard". Agreed plan (DONE — see above). The user enabled
Anthropic's `frontend-design` plugin on 9 Oct (takes effect in a new session). Tools to use:
1. `frontend-design` skill — load it FIRST and build the redesign with it.
2. Anthropic **Design** plugin (already enabled; skills `design:design-critique`, `design:accessibility-review`,
   `design:ux-copy`, `design:design-system`) — use AFTER building: critique the live screens, fix, accessibility
   pass (contrast, keyboard, reduced motion), plain-English copy for results.
3. `dataviz` skill for charts (equity curve, price + trades).
Audience: the professor (Prof. Ashok Harnal) — must look professional, calm, credible; no gimmicks.
- One app, no separate SuperAgent mode/warp. Three sections: **Test a bot** (TradingAgents original from GitHub +
  4 rule bots + saved strategies → backtest → plain-English verdict → paper trade), **Build your own** (idea/file →
  rules), **Paper accounts**.
- Hide Purple's "Analyst Team" rebuild and the not-runnable CrewAI card; Deploy becomes a small "Download code" link.
- Backtest and paper trading must be deliberate, easy to follow, and easy to interpret (explain the result):
  e.g. clear steps (what / on which stock & period / costs assumed → run → verdict), a plain-English verdict card
  ("beat / lagged buy & hold by X%, worst drop Y%, Z trades, what that means"), key assumptions stated.
- Keep working: backend endpoints, TradingAgents engine choice (Local Qwen / Gemini / Claude with paid approval),
  rule editor, versions, uploads, paper accounts, all 55 backend tests.
- Restore point: commit 82579f0 (pre-redesign UI). Plan recorded in 37daa1e.
- Main frontend files: `frontend/src/App.tsx`, `components/{Home,SuperAgent,Workspace,Results,RuleEditor,Chat,
  LineChart,GraphView,Warp}.tsx`, `styles.css` (one large file; later "declutter"/"light SuperAgent" blocks override
  earlier rules — a clean rewrite is welcome).

## Other pending user decisions

- Full in-app TradingAgents run (~10–20 min) — ask before doing it.
- AI provider for the whole app (local Qwen vs paid); real NSE data source/licensing; FRED key (free).
- Optional PDF library (pypdf) for better PDF reading — install needs approval.

## Git

- `master` latest: 82579f0 cloud engine choice + decluttered light UI · 37daa1e redesign plan (+ this handoff
  update). Earlier: 8da0e0e single upload + original TradingAgents, a023be6 money-ideas handoff (unrelated).
- No global git identity; commits use one-off `git -c user.name="Prateek" -c user.email="prateeksinghamu@gmail.com"`.
- **Auto-commit (user rule since 3 Oct):** commit after each finished change, local only, never push, stage files
  explicitly, check for secrets first.

## Run

- One click: `purple\Start Purple Trade.cmd` → http://127.0.0.1:8780.
- Dev: `.claude/launch.json` → `purple-api` (8780; runs via PowerShell that loads GOOGLE_/ANTHROPIC_API_KEY from
  the user env; restart after backend edits) and `purple-web` (5173). Open **http://localhost:5173** (Vite listens on
  IPv6 only; 127.0.0.1:5173 fails). Servers stop when a chat ends — start them again with preview_start.
- Ollama qwen3:8b at 127.0.0.1:11434. DB `purple/backend/data/purple.sqlite3` (test paper account
  "TradingAgents Analyst Team · SAMPLE" exists). TradingAgents data/logs: `purple/external/ta_home/`.

## Working rules

- No uploads, mail, publishing, accounts, spending or installs without explicit approval.
- **Ask before redoing/repeating finished work** (re-runs, rebuilds, rewrites) — token cost.
- Never execute user-uploaded or AI-generated code. Only curated agents run.
- Verify live before claiming done; mark unverified claims; no subagents unless asked; terse replies.
