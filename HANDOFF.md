# Purple Trade — new-chat handoff (updated 25 October 2026: strategy lab week 1)

**START HERE: section "Current state (15 Oct 2026)" is authoritative. Everything below it is history.**

Read this first, then `purple/README.md`. Root `CLAUDE.md` section 1 describes the OLD root app — superseded; do not
extend or reuse it. Leave the TCS/Infosys RAG files untouched (they share the CIS repo).

## Current state (15 Oct 2026; Beat the market added 22 Oct)

**Friends' accounts (23 Oct 2026, evening; NOT pushed yet)**
- User: owner is primary; up to 10 friends register themselves (open sign-up, first 10), see the owner's bot
  read-only, use the tools privately with their own free AI key, cannot change core features.
- `purple_api/accounts.py` (only when PURPLE_PASSWORD is set; laptop and public demo unchanged): sign-in page
  instead of the browser's Basic prompt; owner = name "owner" + PURPLE_PASSWORD (Basic header still accepted);
  friends register (PURPLE_MAX_USERS, default 10; scrypt hashes; 30-day HttpOnly session cookies, hashed in DB;
  20 failed logins per IP per 15 min). Friends get 403 on POST /api/desk*, review save, /api/auth/users;
  `NoServerAI` instead of the server's AI; the live loop never decides friends' AI paper accounts.
- Store: tables `users`, `sessions`; `owner` column on strategies and paper_accounts (NULL = owner);
  `Store._mine()` filters lists/gets by `accounts.scope()` (contextvar set per request; None = no filter).
- UI: `SignIn.tsx` (sign in / create account, places left), view-only banner, no Start/Stop/Decide or rule Remove
  for friends, sign-out in the sidebar, owner-only "Friends' accounts" card in More (list, remove). Dashboard launch
  text now says thirteen analysts. Verified locally on a copy of the live DB (port 8784, test password).
- After the push the owner signs in once on the new page with name `owner` and the usual password.

**Crash guard follow-ups (23 Oct 2026, afternoon)**
- LIVE (219b2a3, pushed 13:56): after a market guard sale the bot records each later bar as `by: "rule:guard"`
  with no AI call and no mood read (verified online: 13:45 bar). Review counts only AI-manager decisions as AI;
  COACH.md reviews guard days even with few AI decisions.
- Committed, NOT pushed (5e7cb4a): `coach.guard_buyback` = crash-day test in the review pack/report
  (`guard_test`): buy the guard-sold shares back once NIFTY closes a 5-min bar 0.2% above its low since the sale
  (Yahoo 5m, 30m panel fallback), hold to the last bar, rupees vs staying in cash. Daily review shows it with a
  running tally; COACH.md 3c: after 5 crash days recommend building it only if it won in total and on 3+ days.
  23 Oct (to ~14:00): bought back 11:10, about +Rs 1,391. 19 Oct (replay) the bounce was fake and it lost.

**Pre-open read (25 Oct 2026, night; pushed)**
- Owner wanted a decision before the open on Asian cues. The 23 Oct test said selling at the open loses (NIFTY
  recovers; its 3-year gain came overnight), so it is tracked, not traded. `purple_api/preopen.py`: live loop reads
  ^GSPC, ^N225, ^HSI, ^INDIAVIX, ^NSEI (`market.quote`) once between 09:00 and 09:15 IST on weekdays into
  `deskpreopen:<bot>`; warning-sign thresholds from 23 Oct, 2+ = flagged. GIFT Nifty is not on Yahoo. Review pack
  `preopen_test` (every day): NIFTY gap, open-to-close, and selling half the company's shares at the day's first
  open and buying back at the last close vs holding, after intraday charges; kept in reports.json. COACH.md 3f:
  tally; after 10 flagged days propose shadow only if flagged days won (6+/10) and other days lost.

**Coach's bench (25 Oct 2026, evening; pushed)**
- Owner: the daily coach should also test strategies after judging the company and the lab. `purple_api/bench.py`
  (stdlib + market): JSON spec from parts (supertrend, ema_cross, macd, donchian, rsi_revert, bollinger_revert,
  range_filter; side; regime bull/bear by NIFTY vs 200-day average the day before; day_trade). Tests on NIFTY with
  futures costs: hourly ~2y (Yahoo 60m, `market.INTERVALS` now has 60m) vs buy-and-hold per unit of worst fall,
  nearby settings x0.7/x1.4 (75% must make money), daily 20y (>= half of buy-and-hold's return per unit of worst
  fall; skipped for day trades). Verdict strong / weak / fail; `--save` appends to `coach/bench.json` (git-ignored,
  uploaded to the dataset). `lab.simulate(flat_eod=True)` = day-trading account. ~2 s per idea.
- COACH.md 3e: one idea a day (three on Fridays), no retests, no tuning; strong (or a useful weak hedge) becomes an
  "owner" idea to add to the lab. Report notes take `tested` [{name, verdict, finding}] (`make_report`).
- First runs (25 Oct): hourly trend WEAK, bear short WEAK, Range Filter day trades FAIL, Donchian FAIL, MACD bull-only
  long WEAK, EMA 9/21 bull-only long STRONG (hourly +12.7%, worst fall -9.4% vs NIFTY +16.3%/-17.0%; daily since
  2007 +168%, worst fall -17.4% vs +403%/-59.4%). Owner added it to the lab: `ema_bull`, shadow from 2026-10-26,
  needs futures only; candidates with a `spec` run through `bench.positions` (same code as the bench).
- Cloud routine reaching Yahoo: UNVERIFIED until its first run.

**Strategy lab, week 1 (25 Oct 2026; commit 3ea8dcb, pushed as 9f7c727 to public main; app look unchanged)**
- Owner's goal: run the bot like a fund that maximises client return for the client's chosen risk, inside the
  trading mandate (no parking cash in bonds). Add strategies gradually, mostly in the back end; retire proven losers.
- Agreed rules: long backtests are the main evidence (10 days of live returns are noise; ~400-1,600 days needed to
  prove an edge); shadow checks behaviour; money moves in steps (shadow -> 10% -> 25% -> full) at 1/3/6-month
  reviews; demote at once on risk breaches, on returns only at reviews; the owner approves every promotion.
- `purple_api/lab.py`: STAGES, RISK_LEVELS (low/medium/high; `PURPLE_RISK_LEVEL`, default medium = today's bot:
  long only, no futures), CANDIDATES with bench evidence, hourly bars from the 30m panel, Supertrend, paper simulate
  (next-hour open fills, NIFTY futures charges), `assess` (risk flags, trade-count check after 20 days, review dates,
  live weight days/(days+250), blocked by risk level), `report`, `markdown`. Reproduces the research backtest exactly
  (+26.65% / +11.89% on Yahoo hourly; hourly-from-30m matches Yahoo 420/420).
- Shadow since 2026-10-26: `trend_hourly` (Supertrend 10x3 hourly, long/short) and `bear_short` (short only while
  NIFTY closed below its 200-day average the day before). Both weak evidence (daily versions lost over 2007-2026);
  both need futures+shorts, so promotion is blocked at the medium risk level.
- Wiring: review pack `lab` + "Strategy lab" Markdown section, `GET /api/desk/lab`. COACH.md 3d = Friday board report;
  3a now waits for the 1- and 3-month reviews before recommending a return to the original five. No UI change.
- Next (weeks 2-3): a small lab card in Daily review; a client risk questionnaire that sets the level; bench the
  analysts the report card grades weakest before retiring any.

**Research 25 Oct 2026: friend's "Brahmastra" Range Filter + popular strategies (REJECTED; nothing built)**
- Range Filter (DonovanWall, 100x3), Supertrend 10x3, EMA 9/21, MACD, Donchian 20/10, RSI 30/70, Bollinger, ORB,
  SMA 50/200, Connors RSI2; textbook settings, signal at close, fill next open, real charges + slippage (stocks
  0.05%, futures 0.01%). Scripts/results: session scratchpad `bt/` (not in git).
- 5-min intraday (59 days): all lose with costs; Range Filter both sides -17.5% stocks / -5.6% futures (+1.2% gross).
  Hourly intraday (Nov 2023-Oct 2026): all lose except Bollinger long +2.5%.
- Daily 2007-2026: buy & hold CAGR 8.8%; every strategy lower (best EMA 9/21 long 5.6%); in bull years B&H averaged
  +25.9%, best strategy +17%. Trend filters cut 2008 losses but miss rallies. Range Filter long 1.8%, both -4.8%.
- Only lead: hourly Supertrend swing on NIFTY futures, positive in all 12 nearby settings (+1 to +27%, B&H +16%,
  smaller drawdowns), but the same rule on daily bars lost; only 3 years of hourly data; needs futures. Not built.

**Research 23 Oct 2026: crash guard, warning signs, short selling (all REJECTED; nothing built)**
- Trigger: on 23 Oct the guard sold at 10:09 (NIFTY 0.7% below its 30-min high after a slow slide) and NIFTY
  then bounced. User asked for faster triggers, come-back-in, cut-half, a 5-min-watched same-day short, and
  pre-open warning signs. Scripts and outputs: session scratchpad `crash/` (not in git).
- 59 days of NIFTY 5-min (30 Jul-23 Oct, 23 Oct partial), NIFTY as the portfolio, real charges + 0.05% slippage:
  no guard -7.01%; current guard (0.7%/30m) -7.34% (fired 2 days); faster triggers worse (0.5%/15m -7.94%, 3 days;
  0.3% fires on 25 days); cut-half and come-back-in no better; same-day short: 144 settings traded, 0 beat no
  guard (best -7.23%, worst -15%). The 8 worst days were slow slides or gap-downs: their biggest 30-min fall was
  0.26-0.74%, so there was no fast crash to catch.
- Warning signs, 3 years daily (733 days, 89 "bad" days with open-to-close <= -0.7%): US -1%/-1.5% overnight, India
  VIX +5/10%, NIFTY -1% yesterday, Japan/HK -1.5%, gap-down 0.5/1%, 2+ signs. They do flag bad days more often
  (up to 28% vs 12%), but on most of those days NIFTY recovers after the open (average open-to-close positive), so
  cutting 50% at the open lost 1-23 points over 3 years in every variant, delivery or same-day, in nearly every
  third. Also: NIFTY's whole 3-year gain came overnight (average open-to-close -0.03%/day).
- Kept the current guard as insurance against a real fast crash (none in the sample). Small open fix: the AI
  manager still meets after the guard fires and writes confusing "move cash into ..." reasons (targets are forced
  to cash); skip the AI while the guard holds cash. Also seen: "AI chief: ValueError: no valid winner".

**Coach report, real costs, steady hands (22 Oct 2026, ~18:00 IST; commit ad92413, pushed 18:06 as bdc0c7d, live)**
- User: the review is the most important part; plain English, judge every bot, whole-system ideas for maximum
  return, show real taxes/charges SEPARATELY (never cut returns), the bot must learn from the review; coach on Opus.
- `purple_api/costs.py`: real Indian bill per day for the bot's trades (delivery STT 0.1% both sides, intraday STT
  0.025% sell, stamp 0.015%/0.003% buy, NSE 0.00297%, SEBI, GST 18% on exchange+SEBI, DP Rs 15.34 per stock sold,
  brokerage 0) + estimated income tax (20% short-term gains FIFO, 30% slab assumed on same-day profit). Rates from
  broker/tax pages (UNVERIFIED against official notices). Paper returns still use 3+5 bps.
- Review pack: `costs` (day + since start) and `report_card` (all 13 analysts' shadow portfolios today/since start,
  trades, real cost, led/used, plus the old-bot twin). 22 Oct: gain Rs 1,521, real bill Rs 1,526 (charges 1,064 +
  tax 462; Rs 26.9 lakh of the 31.9 lakh turnover was same-day).
- Coach report: `coach report --notes <json>` = `make_report` (headline, story, grades per analyst strong/average/
  weak + trust more/same/less, costs_note, advice_check, rule_changes, ideas coach/owner, watch) joined with code
  numbers -> `coach/reports.json` (git-ignored; dataset; pulled by hfsync like the journal). `GET /api/desk/journal`
  returns `{reports, entries}`; Daily review shows the report (numbers, costs box, report card, advice, changes,
  ideas, watch), journal cards only for days without a report.
- Manager learns: `chief_prompt(..., report=coach.latest_report(bot, bar), switch_pct)` adds the real switch cost,
  the last day's bill vs gain and the report card grades; CHIEF_SYSTEM explains costs, grades and steady hands.
- Steady hands in code (company only, from `desk.STEADY_FROM` 2026-10-23 09:15): no selling a stock bought earlier
  the same day, no buying back one sold that day, skip reweights under 10 points on kept stocks (crash guard exempt).
  Twin and backtests unchanged.
- COACH.md rewritten (plain-English rules, grades, costs, ideas, report step, reports.json "already reviewed"
  check). Routine trig_01SBtXHPFWDFrRSvKeRKSLL8 now model claude-opus-5-5 with a new prompt; the API dropped the
  `effort` field, so extra-high effort is NOT set (check the routine page). A sample 22 Oct report (written by this
  session) was uploaded to the dataset (`coach/reports.json`, user approved) and shows live in Daily review.

**Daily review tab (22 Oct 2026, evening; commit 2893688, pushed 17:36 as 4eecbfd)**
- New HF token `purple-coach-cloud` (fine-grained, read+write on the state dataset only) in the cloud env; test run
  of the routine passed (whoami Prat8118, dataset downloaded, skipped because the laptop had reviewed 22 Oct).
- Nav item Daily review `#/review` (`components/Review.tsx`): one card per journal entry, newest first: Summary (else
  the Result line), went well / went wrong / rule changes / watch next, rest under More detail.
  `GET /api/desk/journal` (`coach.parse_journal`); online, `hfsync.pull_journal` copies `coach/journal.md` from the
  dataset at startup and every 10 min (pull only). COACH.md now asks for a plain `- Summary:` bullet first; the cloud
  routine reads COACH.md from GitHub, so this needs the push. 22 Oct's entry has no Summary.

**Daily coach in the cloud (22 Oct 2026, ~17:00 IST)**
- Cloud routine trig_01SBtXHPFWDFrRSvKeRKSLL8 "Purple Desk daily coach (16:30 IST)": cron `0 11 * * 1-5` UTC, Sonnet 5.5,
  Default cloud env, repo prateekks-analytics/purple-trade, no connectors. Needs `HF_TOKEN` in the environment (user
  adds it). Follows `purple/coach/COACH.md` (shared instructions; paths relative to the purple folder).
- Journal and reviews live in the dataset (`coach/journal.md`, `coach/reviews/`), playbook at `playbook.md` (the
  bot syncs it). Whoever runs first writes today's journal entry; the other skips.
- Desktop task `purple-desk-coach` is now the backup at 18:00 IST; `/coach-bot` points to COACH.md.
- First review (22 Oct, laptop): company +0.30% vs NIFTY -0.54% vs twin +0.03%; 29 trades (~Rs 32 lakh turnover);
  added trial R1 against churn (keep holdings unless the stock list changes; no same-day cash round trips).

**Analyst company (22 Oct 2026, ~11:50 IST, commit f4ae831, live as 10a5e87)**
- User asked for 10-15 bots with different behaviours and a manager that synthesises them like a company.
- `desk.AGENTS` = 13 analysts with `team`: Price action (momentum, trend, dip, breakout, contrarian), Technical (tech:
  MACD 12/26/9 + Bollinger 20/2 + volume + RSI<70), Fundamentals (growth, quality from `deskfund` annual reports
  fetched weekly for the 10 base stocks; longterm from daily bars), News & social (news = news mood + growth
  tie-break; social = Reddit-post mood, scored apart from news in the same single mood call), Risk-takers (highbeta:
  `leaders.risky`, 3 most volatile rising stocks of WIDE, picks per day in `deskrisky:` + bot id, only when NIFTY >=
  its 30m EMA50), Defence (guard). Plus CORE (rule) in uptrends. `OLD_IDS` = the original five.
- Context for analysts: `coach.context(db, bot, p)` (daily_context, fundamental_scores, social index, risky per bar).
  Base analysts trade only `UNIVERSE`; highbeta trades its picks (fetched as extra panel symbols).
- Manager: CHIEF_SYSTEM = portfolio manager; prompt groups analysts by team; returns targets (any panel symbol,
  `parse_chief(..., allowed=)`), winner (lead) and `uses`; told not to chase two-day records. Prompt ~1.2k tokens.
- Replay (no AI, 40/20/10 days): record-chase over 13 analysts -6.90%/-0.19%/+3.26% vs original five
  -0.67%/+1.41%/+3.58% with ~2x trades. So the no-AI fallback judges only OLD_IDS and the backtest page shows OLD_IDS.
- Old-bot twin: `coach.twin` (OLD_IDS, judge by record, no AI, from bot start) in `/api/desk` `twin` and the review
  summary (`twin_pct`). `/coach-bot` step 3a: after 10 trading days, if the company trails the twin by >0.5 pts
  since start, tell the user to go back to the original five.
- Render deploys: the 11:35 deploy waited ~10 min between "Deploying" and server start (free tier); the old
  instance keeps trading meanwhile. A decision made by the old instance in the overlap may be decided again by the
  new one (same bar), which is harmless.

**Core momentum strategy (22 Oct 2026, ~11:35 IST, commit 1b82261, live as 8ce69ee)**
- Wide-universe lab (scratchpad only): 97 NSE large+mid caps, 5y daily Yahoo, long only, 8 bps/side, decide on close,
  fill next open. Picked on 2022-11..2024-10 (NIFTY +17%/yr), judged on 2024-10..2026-10 (NIFTY -3.3%/yr, unseen).
  Top in-sample strategies (+60-73%/yr) lost up to 22%/yr out of sample WITHOUT a market filter. With the filter
  (in stocks only while NIFTY > its 200-day average) 3-month momentum was positive out of sample in 17/18 settings
  (top 5, monthly: +4.3%/yr, max DD -9.4%); 49% of out-of-sample days were in cash. Survivorship bias: today's list.
- `purple_api/leaders.py`: WIDE (96 symbols), PICKS 5, LOOKBACK 63, HOLD 21, TREND 200, WEIGHT 0.19. `regime`,
  `strongest`, `today` use only closes before the day. desk_routes: `refresh_daily` (once per weekday from 08:30, ~97
  daily downloads in a thread), `core_for` (stored per day under `deskcore:` + bot id; stale daily data -> off),
  `decide` -> winner "core", by "rule:core" (no AI call) while on; else the five agents on the 10 base stocks only
  (`coach.base_panel`). Panel symbols = base + every stock the core ever picked (new picks fetch 1mo of 30m bars).
  View: `core` block + a 6th agent card; Dashboard shows "Mode: ...". On 22 Oct NIFTY was 5.3% below its 200-day
  average (last above 26 Feb 2026), so the core is OFF; it would hold COFORGE, DIVISLAB, KOTAKBANK, TVSMOTOR, HCLTECH.

**Research 22 Oct 2026 (late morning): what was tested and rejected (do not redo without new data)**
- Replays on real Yahoo prices (60 days of 5m + 30m, 2 years daily, 4 years annual fundamentals), judge-by-record,
  fees and slippage included. Windows: last 40/20/10 trading days to 22 Oct.
- Decision interval: 30 min beats 5 min in every window (40d: -0.67% vs -2.55% same signals vs -4.59% short signals).
- Team mix of all agents (equal or by record) loses to one winner (40d -3.58% / -0.96% vs -0.85%), 2-3x the trades.
- Crash guard (SHIPPED, d3a58b7): NIFTY -0.7% in 30 min -> all cash for the day; stock -5% from high since bought.
  Per-stock stops of 1.5-4% lost 0.5-1.6 pts over 40 days.
- Technical analyst agent (MACD 12/26/9 + Bollinger 20/2 + volume + RSI<70): own portfolio -9.1% over 40 days;
  adding it made the desk worse or equal. REJECTED.
- Long-term leader agent (above 50d > 200d SMA, 63-day strength vs NIFTY, top 4): +0.3-0.4 pts in the 60-day
  replay but over 13 months on daily data -1.28%/month vs NIFTY -0.33% (beat NIFTY 4/13). REJECTED as noise.
- Quality filter (avoid bottom 3 by profit growth + revenue growth + ROE, reports public +75 days): +2-4 pts in the
  60-day replay (avoided AXISBANK, HDFCBANK, ITC) but over 2 years the "weakest" beat the rest in 13 of 21 periods
  (avg -1.1 pts). REJECTED as luck. Valuation skipped (INFY reports in USD); results-date avoidance untestable
  (no free history of results dates); richer AI fact sheet untestable without many AI calls.
- Experiment code was reverted (not in git); scripts were in the session scratchpad only.

**Purple Desk online: Render + Hugging Face dataset backup (22 Oct 2026, morning after)**
- LIVE since 22 Oct ~10:12 IST: https://purple-desk-qgjw.onrender.com (Render service srv-dbcp75lg1s2s73e2jk70,
  Blueprint purple-desk, commit 748ff42). Password = PURPLE_PASSWORD (user typed it; any user name). The laptop
  server was stopped at 10:10 after a fresh DB upload; do NOT start `purple-api` on 8780 with the live loop again
  while the online bot runs (two bots). `purple/coach/hub.txt` = the state dataset, so `/coach-bot` works online.
- Local DB bot f87d385cea46 set to 'stopped' (22 Oct 10:20) so the laptop can never run a second copy; the online
  bot is the truth. Scheduled task `purple-desk-coach` (desktop app, weekdays 16:30 IST, Auto mode) runs /coach-bot
  on the online state; it runs on next app launch if the app was closed. User chose to keep the public demo.
- AI (22 Oct 10:36): Render env GROQ_API_KEY added; `default_provider` = ChainProvider: Groq `openai/gpt-oss-120b`
  first (free ~1K req/day per Groq docs, labelled Developer plan), then Gemini (3.8 Flash has only 20 free req/day;
  3.7 also 20; 3.5 worked). gemini-4-argon has no free-tier quota. Decisions record `by` = the provider that answered.
  The in-app 'Connect an AI' key is browser-only and never used by the live bot.
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
