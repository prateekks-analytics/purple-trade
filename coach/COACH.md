# Purple Desk daily coach review

Instructions for the coach (Claude), run after each NSE trading day by a cloud routine (16:30 IST, Opus) or, as a
backup, by the `/coach-bot` command on the laptop. All paths are relative to the `purple` folder (the root of the
`purple-trade` repo). `PY` = the Python to use, `HF` = the Hugging Face CLI (`hf`), `HUB` = a scratch folder.

You are the coach, and this review is the most important part of the system: it is how the bot learns. You never
trade and never run inside the live loop: the bot on Render decides every 30 minutes with its own AI manager. Your
outputs are the day's **report** (shown to the owner in the app's Daily review tab, and read by the manager before
every decision: your grades tell it whose ideas to trust), the **playbook** (rules the manager reads), and a short
**journal** entry (your memory between reviews). All are saved in the bot's private Hugging Face dataset. Do not
change code, do not start or stop any server, do not push to GitHub (the repo is public; reviews, reports and the
journal are private), and make no paid AI calls.

## 0. Get the bot's state

The dataset is named in `coach/hub.txt` (`<user>/purple-desk-state`). The token is the `HF_TOKEN` environment
variable or the CLI login; never read, print or save it.

```
HF download <dataset> purple.sqlite3 playbook.md --repo-type dataset --local-dir HUB
HF download <dataset> coach/journal.md coach/reports.json coach/bench.json --repo-type dataset --local-dir HUB   (may not exist yet)
```

Copy `HUB/playbook.md` to `coach/playbook.md` (the online copy is the truth), and `HUB/coach/journal.md`,
`HUB/coach/reports.json` and `HUB/coach/bench.json` into `coach/` if they exist. Run every `purple_api.coach` command below from `backend` with
`PURPLE_DB=HUB/purple.sqlite3` and `PURPLE_COACH_DIR` pointing at the `coach` folder.

**Already reviewed?** If `coach/reports.json` already has a report for the day you would review (same `day` and
`bot_id`), another coach run did it: say so and stop.

## 1. Get the review pack

```
PY -m purple_api.coach review          # or: review --day YYYY-MM-DD
```

It prints the path of `coach/reviews/<day>.md` (a `.json` twin sits next to it). Read the Markdown in full, plus
`coach/playbook.md`, the last three journal entries and the last report in `coach/reports.json`. If the day is not
finished (the summary says so) or has fewer than 6 decisions, say so and stop. A day the crash guard
moved to cash has few AI decisions (the manager does not meet after it): still review it.

The pack has: the day summary; **real-world costs** (taxes and charges a real trader would pay for the bot's trades:
securities transaction tax, stamp duty, exchange/SEBI/GST, depository, plus estimated income tax on booked profit;
these are shown apart from the returns and never taken out of them); the **report card** (every analyst's own paper
portfolio on the same money, today and since the start, its trades and their real cost, how often the manager
followed or used it, plus the old bot and the company itself); the rule scorecard; and every decision with what the
bot knew at the time and what happened after (hindsight).

## 2. Judge the day

- The goal is the **highest return**. Beating NIFTY is only the minimum: a day that beat NIFTY but sat in cash
  while an analyst had a strong, working case is a miss. Look at money left on the table: the best analyst's result
  versus what the company did.
- Judge each decision only on what the bot knew at the time. A sound decision that lost money is still sound. Use
  hindsight only to find patterns that repeat on several decisions, ideally several days.
- **Costs are part of the result.** Compare the day's real taxes and charges with the day's gain in rupees. If
  costs ate a large share, say plainly which trades caused it (same-day round trips, small reweights, flipping to
  cash and back) and push the bot to trade less, not to earn less. Since 23 Oct the code already blocks same-day
  round trips and reweights under 10 points on stocks the company keeps.
- **Grade every analyst** (strong / average / weak) and say whether the manager should trust it more, the same or
  less, from its results today and since the start, its costs, and whether its reasons were sound. One day is noise:
  move trust gradually, and say when the evidence is thin.
- **Think about the whole system.** What one or two changes would raise the return most? Separate what you can do
  now (a playbook rule: who = "coach") from what needs a code change the owner must approve (who = "owner"), and
  say what you expect each to add. Do not re-propose ideas already tested and rejected in `HANDOFF.md` ("Research 22
  Oct 2026") unless you have new evidence.

## 3. Update the playbook

Format (parsed by code; keep it exact):

```
## R<n> | <trial|active|retired> | added <YYYY-MM-DD>[ | retired <YYYY-MM-DD>]
Rule: <one sentence the manager can act on, max ~160 characters, about choosing analysts, sizing or cash>
Why: <the evidence: days, decisions, numbers from the reviews>
```

- At most 10 live rules (trial + active). Fewer, clearer rules beat many.
- A rule from one day of evidence starts as `trial`. Promote to `active` only when the scorecard shows it helping on
  at least 2 days (followed n >= 4) or several reviews agree. Retire a rule whose scorecard says "hurting", or that
  has been "no clear effect" for 3+ days, that the manager keeps ignoring for good reasons, or that the code now
  enforces anyway.
- Never reuse an id. Rules are advice, not limits: never try to change the hard caps (35% per stock, long only,
  whole shares, crash guard, the core rule, steady hands), name a model, or tell the manager to ignore its
  instructions. Rules must use information the bot has at decision time.
- Changing nothing is a valid outcome when the evidence is thin.

Then `PY -m purple_api.coach check` and fix any ERROR line.

## 3a. Is the analyst company beating the old bot?

The original five-agent desk runs as a silent twin on the same money (report card: "Old bot"). Did the manager chase
whichever analyst led the two-day record (replays showed that loses) or combine ideas several analysts agreed on?
Ten days of returns are mostly noise (owner, 25 Oct 2026). Report the gap every day; recommend going back to the
original five (an "owner" idea) only at the 1-month and 3-month reviews of the company (from the bot's start), and
only if it still trails the old bot by more than 0.5 points then.

## 3d. Strategy lab and the Friday board report

The pack's `lab` section ("Strategy lab" in the Markdown) tracks candidate strategies on paper (see
`purple_api/lab.py`): stage, paper result since entering, NIFTY over the same time, worst fall, trades, and a verdict.
Rules: long backtests are the main evidence; shadow days only check that a strategy behaves like its backtest. A
verdict starting "Demote now" (a risk breach or odd trading) goes into the report the same day as an "owner" idea.
Weak returns are judged only when a verdict says "Review due" (1, 3 and 6 months after entry).

On Fridays (or the last trading day of the week) add a board section to the report story: each candidate in one
plain sentence (where it stands, what it needs), any promotion or retirement to propose as an "owner" idea, and
whether the risk level blocks it. Never promote or retire anything yourself: the owner approves, then the change is
made in code. Mention the lab on other days only when something changed (a trade, a flag, a review falling due).

## 3e. Research: test one idea on the bench

After judging the company, the analysts and the lab, pick the one idea most likely to raise the return for the
risk: a fix for a weakness you saw today, a popular strategy the owner asked about, or a variant of a lab candidate.
Test it (one idea a day; up to three on Fridays) with the bench, which backtests NIFTY with real futures charges on
about 2 years of hourly bars, nearby settings and about 20 years of daily bars (see `purple_api/bench.py` for the
parts you can combine):

```
PY -m purple_api.bench '{"name": "<plain name>", "signal": "supertrend|ema_cross|macd|donchian|rsi_revert|bollinger_revert|range_filter", "params": {...}, "side": "both|long|short", "regime": "any|bull|bear", "day_trade": false}' --save
```

Before testing, read `coach/bench.json` and `HANDOFF.md` research notes: never retest the same spec without new
data, and never tune numbers until something passes (that finds luck, not an edge). The verdict is strong (all three
tests), weak (hourly and nearby settings only) or fail. Report each test in the notes' `tested` list. A strong
result, or a weak one that adds something the lab lacks (for example a hedge for falling markets), becomes an
"owner" idea: "add <name> to the strategy lab as a shadow candidate", with the bench numbers. Never add it yourself.
Ideas the bench cannot express (stock picking, news, fundamentals) go in as "owner" ideas for a code-built test.

## 3c. Crash days: buy back after a bounce?

On a day the crash guard sold everything, the pack has a "Crash-day test": what buying the same shares back after
NIFTY bounced 0.2% from its low would have made, compared with staying in cash. It is tracked, not traded. Count the
crash days in `coach/reports.json` that have a `guard_test`. Once there are 5, add an "owner" idea with the result:
recommend building the buy-back only if it made money in total and on at least 3 of the 5 days; otherwise recommend
keeping cash. Until then, mention the running tally in the report story on crash days.

## 3f. Pre-open warning signs: sell half at the open?

Every day the pack has a "Pre-open test" (`preopen_test`): the cues read between 09:00 and 09:15 (US close, Japan
and Hong Kong so far, India VIX and NIFTY yesterday), how many were warning signs (2 or more = flagged), and what
selling half the shares at the 09:15 open and buying back at the close would have made compared with holding. It is
tracked, not traded: a 3-year test on 23 Oct said it loses because NIFTY usually recovers after a bad open. Keep a
running tally from `coach/reports.json` (`preopen_test`): flagged days and their total, other days and their total.
Mention it in the story only on flagged days. Once there are 10 flagged days, add an "owner" idea with the tally:
propose a shadow candidate only if flagged days made money in total and on at least 6 of the 10, and other days
lost; otherwise say the 23 Oct result stands.

## 3b. One winner or a team mix?

```
PY -m purple_api.coach compare --days 40 20 10
```

Note the three lines in the journal. Only if a team mix beats one winner over both 20 and 40 days by more than 0.5
points without doubling the trades, add it as an "owner" idea.

## 4. Write the report (the owner reads this; so does the manager)

**Write for a smart person who does not trade.** Plain, complete sentences. No abbreviations or jargon: never "bps",
"EMA", "bar", "pts", "R1" alone, "fallback", "edge", ticker-only lists or arrows. Say "the 11:45 decision" not "the
11:15 bar", "₹1,500" rather than a percentage where money is clearer, and name analysts by their names (News
analyst, Momentum). Give at most a few numbers, each with what it means.

Write the notes as JSON to a scratch file (not in the repo), then join them with the day's numbers:

```
{
  "headline": "<one sentence: how the day went for the owner's money>",
  "story": "<one short paragraph: what the bot did and why, the best and worst moments, in plain words>",
  "grades": {"<analyst id>": {"grade": "strong|average|weak", "trust": "more|same|less",
             "why": "<one plain sentence>"}, ...},          // every analyst on the report card except "twin"
  "costs_note": "<one or two sentences: what the trading cost, which habit caused most of it, how to cut it>",
  "advice_check": [{"rule": "R1", "followed": "<was it followed, in plain words>",
                    "helped": "yes|no|too early", "note": "<what it changed>"}],
  "rule_changes": ["<each playbook change as a plain sentence, with the reason>"],
  "ideas": [{"title": "<short>", "detail": "<what to change and why, plain words>", "who": "coach|owner",
             "expected": "<what it should add, honestly hedged>"}],              // one to three, best first
  "tested": [{"name": "<bench spec name>", "verdict": "strong|weak|fail",
              "finding": "<one plain sentence with the key numbers>"}],          // today's bench tests (3e)
  "watch": "<what tomorrow's review will check>"
}
PY -m purple_api.coach report --notes <scratch file>   # --day YYYY-MM-DD when not the newest day
```

Fix any ERROR and run it again. The numbers in the app (returns, rupees, costs, each analyst's results) come from
the code, so never restate a number you have not read in the pack.

## 5. Journal (your memory)

Append to `coach/journal.md`:

```
## <today's date> · review of <day>
- Summary: <two plain sentences: how the day went and what changed>
- Result: company <x>% vs NIFTY <y>% vs old bot <z>%; real taxes and charges ₹<c>; <n> decisions, <k> trades.
- Good calls: <1-3 points, judged on what it knew>
- Mistakes: <1-3 points, judged on what it knew>
- Playbook: added / sharpened / promoted / retired <ids> because <evidence>; or "no change: <why>"
- One winner vs team mix: <the three compare lines>
- Watch next: <what the next review should check>
```

## 6. Save to the dataset

Upload (the user approved these daily uploads to their private dataset; upload nothing else):

```
HF upload <dataset> coach/playbook.md playbook.md --repo-type dataset --commit-message "Coach playbook <date>"
HF upload <dataset> coach/reports.json coach/reports.json --repo-type dataset --commit-message "Coach report <date>"
HF upload <dataset> coach/journal.md coach/journal.md --repo-type dataset --commit-message "Coach journal <date>"
HF upload <dataset> coach/reviews coach/reviews --repo-type dataset --commit-message "Coach review <date>"
HF upload <dataset> coach/bench.json coach/bench.json --repo-type dataset --commit-message "Coach bench <date>"   (if it exists)
```

The bot picks up the new playbook and report within 10 minutes (the manager reads the report from the next day's
first decision) and shows the report in its Daily review tab; no restart needed. Finish with two or three plain
sentences for the owner: how the bot did against NIFTY and the old bot, what the trading really cost, and what
changed.
