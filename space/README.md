---
title: Purple Desk
emoji: 📈
colorFrom: purple
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# Purple Desk (private)

A paper-money portfolio bot for 10 large NSE stocks. Every 30 minutes during market hours five strategist agents
propose a portfolio, an AI chief (Google Gemini, free tier) picks the winner and the bot paper-trades it. No real
money, no broker.

Secrets (Space settings → Variables and secrets): `GOOGLE_API_KEY` (Gemini) and `HF_TOKEN` (a write token). The
server keeps its database and coach playbook in the private dataset `<your name>/purple-desk-state`, so restarts do
not lose the bot's history. Keep this Space **private**: anyone who can open it can start or stop the bot.

Free Spaces sleep after about two days without visits: open the Space at least once a day.
