# Purple Trade web version (e.g. Hugging Face Spaces "Docker" or Render). Each visitor connects their own AI key
# in the app; keys stay in their browser and are never stored on the server.
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml ./backend/
COPY backend/purple_api ./backend/purple_api
RUN pip install --no-cache-dir ./backend
COPY --from=ui /ui/dist ./frontend/dist
ENV PURPLE_DIST=/app/frontend/dist PURPLE_DB=/tmp/purple/purple.sqlite3 PURPLE_HOSTED=1
EXPOSE 7860
CMD ["sh", "-c", "mkdir -p /tmp/purple && uvicorn --factory purple_api.main:create_app --host 0.0.0.0 --port ${PORT:-7860}"]
