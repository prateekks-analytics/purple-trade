"""Keep the bot's state across Hugging Face Space restarts (free Spaces have no persistent disk).

When HF_TOKEN is set and a state repo is known (PURPLE_STATE_REPO, else <SPACE_AUTHOR_NAME>/purple-desk-state), the
server restores the SQLite database and the coach playbook from that private dataset at startup, backs the database
up when it changed (at most every 10 minutes, and on shutdown) and syncs the playbook both ways: Claude uploads a new
playbook from the laptop after /coach-bot; a rule removed in the app is uploaded from here. Off everywhere else.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import time
from pathlib import Path

DB_FILE, PLAYBOOK_FILE = "purple.sqlite3", "playbook.md"
EVERY = 600  # seconds between backups / playbook checks


def repo_id() -> str | None:
    if os.environ.get("PURPLE_STATE_REPO"):
        return os.environ["PURPLE_STATE_REPO"]
    author = os.environ.get("SPACE_AUTHOR_NAME")
    return f"{author}/purple-desk-state" if author else None


def _sha(b: bytes | None) -> str | None:
    return hashlib.sha256(b).hexdigest() if b is not None else None


class HubStore:
    """The two calls the sync needs, on a private Hugging Face dataset (huggingface_hub is imported only here)."""

    def __init__(self, repo: str, token: str):
        from huggingface_hub import HfApi
        self.api, self.repo = HfApi(token=token), repo

    def ensure(self) -> None:
        self.api.create_repo(self.repo, repo_type="dataset", private=True, exist_ok=True)

    def download(self, name: str) -> bytes | None:
        from huggingface_hub import hf_hub_download
        try:
            with tempfile.TemporaryDirectory() as d:
                return Path(hf_hub_download(self.repo, name, repo_type="dataset", token=self.api.token,
                                            local_dir=d)).read_bytes()
        except Exception as e:  # noqa: BLE001
            # Only "the hub answered: no such file" means nothing saved yet. Offline (LocalEntryNotFoundError) must
            # raise, or a fresh empty database would later overwrite the saved one.
            if type(e).__name__ == "RemoteEntryNotFoundError":
                return None
            raise

    def upload(self, name: str, data: bytes, message: str) -> None:
        self.api.upload_file(path_or_fileobj=data, path_in_repo=name, repo_id=self.repo, repo_type="dataset",
                             commit_message=message)


class Sync:
    def __init__(self, hub, db_path: str | Path, coach_dir: str | Path):
        self.hub, self.db_path, self.coach_dir = hub, Path(db_path), Path(coach_dir)
        self.db_sha: str | None = None
        self.pb_sha: str | None = None  # playbook as last agreed with the hub
        self.last = 0.0
        self.error: str | None = None
        self.restored = False

    @property
    def playbook(self) -> Path:
        return self.coach_dir / PLAYBOOK_FILE

    def restore(self) -> None:
        """Before the database is opened: bring back the last saved database and playbook. If the hub cannot be
        read, backups stay off for this run (so an empty database never replaces the saved one)."""
        try:
            self._restore()
            self.restored = True
        except Exception as e:  # noqa: BLE001
            self.error = f"restore failed, backups off until restart: {type(e).__name__}: {str(e)[:160]}"

    def _restore(self) -> None:
        getattr(self.hub, "ensure", lambda: None)()
        data = self.hub.download(DB_FILE)
        if data:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.db_path.write_bytes(data)
            self.db_sha = _sha(self.snapshot())  # compare like with like: backups are snapshots
        pb = self.hub.download(PLAYBOOK_FILE)
        if pb is not None:
            self.coach_dir.mkdir(parents=True, exist_ok=True)
            self.playbook.write_bytes(pb)
            self.pb_sha = _sha(pb)

    def snapshot(self) -> bytes:
        """A consistent copy of the live database (sqlite's online backup, safe while the server writes)."""
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / DB_FILE
            src, dst = sqlite3.connect(self.db_path), sqlite3.connect(out)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            return out.read_bytes()

    def backup(self) -> bool:
        data = self.snapshot()
        if _sha(data) == self.db_sha:
            return False
        self.hub.upload(DB_FILE, data, "Purple Desk state backup")
        self.db_sha = _sha(data)
        return True

    def sync_playbook(self) -> str:
        """Three-way: the hub changed -> take it; only this copy changed -> upload it; both -> the hub wins."""
        remote = self.hub.download(PLAYBOOK_FILE)
        local = self.playbook.read_bytes() if self.playbook.exists() else None
        r, l = _sha(remote), _sha(local)
        if r == l:
            self.pb_sha = r
            return "same"
        if r != self.pb_sha and remote is not None:
            self.coach_dir.mkdir(parents=True, exist_ok=True)
            self.playbook.write_bytes(remote)
            self.pb_sha = r
            return "pulled"
        if local is not None:
            self.hub.upload(PLAYBOOK_FILE, local, "Coach playbook changed in the app")
            self.pb_sha = l
            return "pushed"
        return "same"

    def tick(self, force: bool = False) -> None:
        if not self.restored:
            return
        if not force and time.time() - self.last < EVERY:
            return
        self.last = time.time()
        try:
            self.sync_playbook()
            self.backup()
            self.error = None
        except Exception as e:  # noqa: BLE001 - never stop the live loop; shown in /api/health
            self.error = f"{type(e).__name__}: {str(e)[:200]}"


def from_env(db_path: str | Path, coach_dir: str | Path) -> Sync | None:
    token, repo = os.environ.get("HF_TOKEN"), repo_id()
    on_space = os.environ.get("SPACE_ID") or os.environ.get("PURPLE_STATE_SYNC") == "1"  # never from the laptop
    if not token or not repo or not on_space:
        return None
    return Sync(HubStore(repo, token), db_path, coach_dir)
