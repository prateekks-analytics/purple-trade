# Builds dist_exe\PurpleTrade.exe (Windows, no install needed for users). Needs: backend\.venv with
# "pip install -e .[dev] pyinstaller", and Node for the UI build.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Push-Location "$root\frontend"; npm run build; Pop-Location
Push-Location "$root\backend"
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --console --name PurpleTrade --icon NONE `
  --distpath "$root\dist_exe" --workpath "$root\build_exe" --specpath "$root\build_exe" --paths . `
  --collect-submodules purple_api --collect-submodules uvicorn `
  --add-data "$root\frontend\dist;frontend_dist" launcher.py
Pop-Location
Write-Host "Built $root\dist_exe\PurpleTrade.exe"
