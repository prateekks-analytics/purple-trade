import sqlite3
import sys
from pathlib import Path

from purple_api import hfsync
from purple_api.store import Store


class FakeHub:
    repo = "me/purple-desk-state"

    def __init__(self, files=None):
        self.files = dict(files or {})
        self.uploads = []

    def download(self, name):
        return self.files.get(name)

    def upload(self, name, data, message):
        self.files[name] = data
        self.uploads.append(name)


def test_restore_backup_and_playbook_three_way(tmp_path):
    db = tmp_path / "live" / "purple.sqlite3"
    coach = tmp_path / "coach"
    seed = Store(tmp_path / "seed.sqlite3")
    seed.add_desk("saved bot", 500_000, 7, "2026-10-21 15:30")
    seed._db.commit()
    hub = FakeHub({"purple.sqlite3": (tmp_path / "seed.sqlite3").read_bytes(), "playbook.md": b"# v1\n"})
    s = hfsync.Sync(hub, db, coach)
    s.restore()
    assert Store(db).list_desks()[0]["name"] == "saved bot" and (coach / "playbook.md").read_bytes() == b"# v1\n"
    assert s.backup() is False  # nothing changed since the restore: no upload
    live = Store(db)
    live.add_desk("second", 100_000, 0, "2026-10-22 09:15")
    assert s.backup() is True and hub.uploads == ["purple.sqlite3"]
    back = tmp_path / "back.sqlite3"
    back.write_bytes(hub.files["purple.sqlite3"])
    assert sqlite3.connect(back).execute("select count(*) from desk_bots").fetchone()[0] == 2
    # Claude uploaded a new playbook from the laptop: the Space takes it
    hub.files["playbook.md"] = b"# v2 from coach\n"
    assert s.sync_playbook() == "pulled" and (coach / "playbook.md").read_bytes() == b"# v2 from coach\n"
    # a rule was removed in the app: this copy goes up
    (coach / "playbook.md").write_bytes(b"# v3 retired R1\n")
    assert s.sync_playbook() == "pushed" and hub.files["playbook.md"] == b"# v3 retired R1\n"
    assert s.sync_playbook() == "same"
    # both changed: the hub (the coach's edit) wins
    hub.files["playbook.md"] = b"# v4 coach\n"
    (coach / "playbook.md").write_bytes(b"# v4 local\n")
    assert s.sync_playbook() == "pulled" and (coach / "playbook.md").read_bytes() == b"# v4 coach\n"


def test_tick_never_raises_and_rate_limits(tmp_path):
    class Broken(FakeHub):
        def download(self, name):
            raise ConnectionError("offline")
    s = hfsync.Sync(Broken(), tmp_path / "x.sqlite3", tmp_path / "coach")
    s.restore()  # offline at startup: never treated as "nothing saved", backups stay off
    assert "restore failed" in s.error and not s.restored
    s.tick(force=True)
    assert "restore failed" in s.error
    s = hfsync.Sync(FakeHub(), tmp_path / "y.sqlite3", tmp_path / "coach")
    s.restore()
    Store(tmp_path / "y.sqlite3")
    s.hub = Broken()
    s.tick()
    assert "offline" in s.error
    s.error = None
    s.tick()  # within 10 minutes: skipped
    assert s.error is None


def test_off_unless_on_a_space_with_token(monkeypatch, tmp_path):
    for k in ("HF_TOKEN", "SPACE_ID", "SPACE_AUTHOR_NAME", "PURPLE_STATE_REPO", "PURPLE_STATE_SYNC"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HF_TOKEN", "x")
    monkeypatch.setenv("PURPLE_STATE_REPO", "me/state")
    assert hfsync.from_env(tmp_path / "a", tmp_path / "c") is None  # a laptop with a token never syncs
    monkeypatch.delenv("PURPLE_STATE_REPO")
    monkeypatch.setenv("SPACE_AUTHOR_NAME", "me")
    assert hfsync.repo_id() == "me/purple-desk-state"


def test_space_stage_copies_code_but_no_private_files(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import space_stage
    files = space_stage.stage(tmp_path / "stage")
    assert {"Dockerfile", "README.md", "backend/pyproject.toml", "backend/purple_api/hfsync.py",
            "frontend/package-lock.json", "frontend/src/App.tsx", "coach/playbook.md"} <= set(files)
    assert not any(f.startswith(("backend/data", "frontend/node_modules", "frontend/dist")) or f.endswith(".env")
                   for f in files)
    assert "Purple Desk online" in (tmp_path / "stage" / "README.md").read_text(encoding="utf-8")


def test_password_gate(monkeypatch):
    import base64

    from fastapi.testclient import TestClient

    from purple_api.main import create_app
    from test_api import FakeProvider
    monkeypatch.setenv("PURPLE_PASSWORD", "s3cret")
    c = TestClient(create_app(store=Store(":memory:"), provider=FakeProvider()))
    assert c.get("/api/health").status_code == 200  # the keep-awake ping needs no password
    assert c.get("/api/desk").status_code == 401  # the app shows its sign-in page
    assert c.get("/api/auth/me").json()["signed_in"] is False
    bad = base64.b64encode(b"me:wrong").decode()
    assert c.get("/api/desk", headers={"Authorization": f"Basic {bad}"}).status_code == 401
    assert c.get("/api/desk", headers={"Authorization": "Basic !!!"}).status_code == 401
    ok = base64.b64encode(b"anyone:s3cret").decode()
    assert c.get("/api/desk", headers={"Authorization": f"Basic {ok}"}).status_code == 200


def test_journal_is_pulled_only(tmp_path):
    coach = tmp_path / "coach"
    hub = FakeHub({"coach/journal.md": b"## 2026-10-22 \xc2\xb7 review of 2026-10-22\n"})
    s = hfsync.Sync(hub, tmp_path / "x.sqlite3", coach)
    s.restore()
    assert (coach / "journal.md").read_bytes() == hub.files["coach/journal.md"]
    assert s.pull_journal() is False  # unchanged
    hub.files["coach/journal.md"] += b"## 2026-10-23 \xc2\xb7 review of 2026-10-23\n"
    (coach / "journal.md").write_bytes(b"local edit")
    assert s.pull_journal() is True and (coach / "journal.md").read_bytes() == hub.files["coach/journal.md"]
    s.tick(force=True)
    assert "coach/journal.md" not in hub.uploads  # never uploaded from the server


def test_reports_are_pulled_too(tmp_path):
    coach = tmp_path / "coach"
    hub = FakeHub({"coach/reports.json": b"[]"})
    s = hfsync.Sync(hub, tmp_path / "x.sqlite3", coach)
    s.restore()
    assert (coach / "reports.json").read_bytes() == b"[]"
