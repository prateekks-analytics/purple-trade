# Purple Desk online (private)

Runs the 30-minute portfolio bot on a free host so it keeps trading (paper money) when the laptop is closed.

- **Render** (used): `render.yaml` at the repo root creates the `purple-desk` web service from `deploy/Dockerfile`
  (free plan, Singapore). In the Render dashboard set `GOOGLE_API_KEY` (Gemini), `HF_TOKEN` (Hugging Face write
  token) and `PURPLE_PASSWORD` (the browser asks for it; any user name). Never commit these.
- **State**: free hosts wipe their disk on restart, so the server restores its database and the coach playbook from
  the private Hugging Face dataset `PURPLE_STATE_REPO` at startup and backs them up every 10 minutes and on
  shutdown (`backend/purple_api/hfsync.py`). If the restore fails, backups stay off so nothing is overwritten.
- **Awake**: the server visits its own `RENDER_EXTERNAL_URL/api/health` every 10 minutes (only when backups are on,
  so the public demo still sleeps). That is about 744 of the 750 free Render hours a month for this one service.
  `deploy/keep-awake.yml` is an optional GitHub Actions ping (needs the gh `workflow` scope to push).
- Only one copy of the bot should run: stop the laptop server once the online one is trading.
