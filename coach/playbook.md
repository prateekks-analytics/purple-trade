# Purple Desk coach playbook

Rules the AI chief reads before every 30-minute decision, written by Claude after each trading day (/coach-bot).
At most 10 live rules (status active or trial). Hard limits in code (35% per stock, long only) always win.
Format per rule: a `## <id> | <active|trial|retired> | added <YYYY-MM-DD>` line (retired rules add
`| retired <YYYY-MM-DD>`), then `Rule:` and `Why:` lines.
