# Purple Desk coach playbook

Rules the AI chief reads before every 30-minute decision, written by Claude after each trading day (/coach-bot).
At most 10 live rules (status active or trial). Hard limits in code (35% per stock, long only) always win.
Format per rule: a `## <id> | <active|trial|retired> | added <YYYY-MM-DD>` line (retired rules add
`| retired <YYYY-MM-DD>`), then `Rule:` and `Why:` lines.

## R1 | trial | added 2026-10-22
Rule: Keep current holdings unless the new idea changes which stocks to own or moves a weight by 10+ points; skip small reweights and same-day cash round trips.
Why: 22 Oct: 29 trades turned over Rs 31.9 lakh on a Rs 5 lakh book (~0.5% of capital in fees+slippage) while the desk made +0.30%; it flipped fully to cash and back twice (10:45/11:45, 12:45/13:45) and reweighted the same five stocks at 14:15, 14:45 and 15:15.
