@echo off
rem Purple Trade (new build). Serves API + built UI at http://127.0.0.1:8780
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
  echo Backend environment missing. See purple\README.md "First-time setup".
  pause
  exit /b 1
)
if not exist "..\frontend\dist\index.html" (
  echo UI not built yet. Run: cd purple\frontend ^&^& npm install ^&^& npm run build
  pause
  exit /b 1
)
start "" http://127.0.0.1:8780/
".venv\Scripts\python.exe" -m uvicorn --factory purple_api.main:create_app --host 127.0.0.1 --port 8780
