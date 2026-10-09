"""Purple Trade desktop launcher (used for the Windows .exe).

Starts the app on this computer, opens it in the default browser and keeps running until this window is closed.
Data lives in %LOCALAPPDATA%\PurpleTrade, so updating the .exe keeps your strategies and paper accounts.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path


def _base() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _free_port(start: int = 8780) -> int:
    for port in range(start, start + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit("No free port found between 8780 and 8829.")


def main() -> None:
    data = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "PurpleTrade"
    data.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PURPLE_DB", str(data / "purple.sqlite3"))
    dist = _base() / "frontend_dist"
    if dist.is_dir():
        os.environ.setdefault("PURPLE_DIST", str(dist))

    import uvicorn
    from purple_api.main import create_app

    port = _free_port()
    url = f"http://127.0.0.1:{port}/"
    print("Purple Trade is running at", url)
    print("Your data is saved in", data)
    print("Keep this window open while you use the app. Close it to stop Purple Trade.")
    if not os.environ.get("PURPLE_NO_BROWSER"):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
