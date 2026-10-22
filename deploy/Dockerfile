# Purple Desk online (Render free web service, or a Docker host). The bot trades every 30 minutes while awake.
# Free hosts have no persistent disk: the server restores and backs up its database and the coach playbook in a
# private Hugging Face dataset (purple_api/hfsync.py). Env: GOOGLE_API_KEY, HF_TOKEN, PURPLE_PASSWORD (see render.yaml).
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
RUN useradd -m -u 1000 user
WORKDIR /app
COPY backend/pyproject.toml ./backend/
COPY backend/purple_api ./backend/purple_api
RUN pip install --no-cache-dir ./backend "huggingface_hub>=1.0,<2"
COPY --from=ui /ui/dist ./frontend/dist
COPY coach/playbook.md /app/seed/playbook.md
ENV PURPLE_DIST=/app/frontend/dist PURPLE_DB=/data/purple/purple.sqlite3 PURPLE_COACH_DIR=/data/purple/coach \
    HF_HOME=/data/purple/hf TZ=Asia/Kolkata PYTHONUNBUFFERED=1
RUN mkdir -p /data/purple/coach && cp /app/seed/playbook.md /data/purple/coach/ && chown -R user /data/purple
USER user
EXPOSE 7860
CMD ["sh", "-c", "uvicorn --factory purple_api.main:create_app --host 0.0.0.0 --port ${PORT:-7860}"]
