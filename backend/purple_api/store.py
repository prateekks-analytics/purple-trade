"""SQLite persistence. Approved versions and completed runs are never mutated."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .engine import Bar

_SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, draft TEXT, chat TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
  id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL REFERENCES strategies(id),
  number INTEGER NOT NULL, body TEXT NOT NULL, hash TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(strategy_id, number)
);
CREATE TABLE IF NOT EXISTS datasets (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, symbol TEXT, source_note TEXT,
  rows INTEGER NOT NULL, first_date TEXT NOT NULL, last_date TEXT NOT NULL,
  hash TEXT NOT NULL, bars TEXT NOT NULL, synthetic INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_sources (
  strategy_id TEXT PRIMARY KEY REFERENCES strategies(id), filename TEXT NOT NULL, kind TEXT NOT NULL,
  content TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL, version_id TEXT, dataset_id TEXT NOT NULL,
  strategy_body TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_decisions (
  cache_key TEXT NOT NULL, date TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (cache_key, date)
);
CREATE TABLE IF NOT EXISTS paper_accounts (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, agent_id TEXT NOT NULL, dataset_id TEXT NOT NULL,
  symbol TEXT, synthetic INTEGER NOT NULL, start_date TEXT NOT NULL, sim_days INTEGER NOT NULL DEFAULT 0,
  capital REAL NOT NULL, created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id() -> str:
    return uuid.uuid4().hex[:12]


class _Rows:
    """Materialised query result with the cursor methods the store uses."""

    def __init__(self, rows: list):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list:
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)
        cols = {r["name"] for r in self._db.execute("PRAGMA table_info(paper_accounts)")}
        if "analyses" not in cols:  # added 3 Oct 2026
            self._db.execute("ALTER TABLE paper_accounts ADD COLUMN analyses TEXT")
            self._db.commit()

    def _q(self, sql: str, args=()):
        # Rows are read while the lock is held: the connection is shared across request threads, and a
        # cursor fetched after release can return another thread's rows (seen as sporadic 500s).
        with self._lock:
            cur = self._db.execute(sql, args)
            rows = cur.fetchall()
            self._db.commit()
            return _Rows(rows)

    # ----- strategies -----
    def create_strategy(self, name: str) -> dict:
        sid, now = _id(), _now()
        self._q("INSERT INTO strategies(id,name,draft,chat,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (sid, name, None, "[]", now, now))
        return self.get_strategy(sid)

    def list_strategies(self) -> list[dict]:
        rows = self._q("""SELECT s.id, s.name, s.updated_at,
                          (SELECT COUNT(*) FROM versions v WHERE v.strategy_id = s.id) AS versions
                          FROM strategies s ORDER BY s.updated_at DESC""").fetchall()
        return [dict(r) for r in rows]

    def get_strategy(self, sid: str) -> dict | None:
        r = self._q("SELECT * FROM strategies WHERE id=?", (sid,)).fetchone()
        if not r:
            return None
        versions = self._q("SELECT id, number, hash, created_at FROM versions WHERE strategy_id=? ORDER BY number DESC",
                           (sid,)).fetchall()
        src = self._q("SELECT filename, kind, content, created_at FROM agent_sources WHERE strategy_id=?",
                      (sid,)).fetchone()
        return {
            "id": r["id"], "name": r["name"], "created_at": r["created_at"], "updated_at": r["updated_at"],
            "draft": json.loads(r["draft"]) if r["draft"] else None,
            "chat": json.loads(r["chat"]), "versions": [dict(v) for v in versions],
            "source": dict(src) if src else None,
        }

    def save_draft(self, sid: str, draft: dict | None, name: str | None = None):
        if name:
            self._q("UPDATE strategies SET draft=?, name=?, updated_at=? WHERE id=?",
                    (json.dumps(draft) if draft else None, name, _now(), sid))
        else:
            self._q("UPDATE strategies SET draft=?, updated_at=? WHERE id=?",
                    (json.dumps(draft) if draft else None, _now(), sid))

    def append_chat(self, sid: str, *messages: dict):
        s = self.get_strategy(sid)
        chat = s["chat"] + [{**m, "at": _now()} for m in messages]
        self._q("UPDATE strategies SET chat=?, updated_at=? WHERE id=?", (json.dumps(chat), _now(), sid))

    def set_source(self, sid: str, filename: str, kind: str, content: str):
        self._q("INSERT OR REPLACE INTO agent_sources(strategy_id,filename,kind,content,created_at) VALUES(?,?,?,?,?)",
                (sid, filename, kind, content, _now()))

    def delete_strategy(self, sid: str):
        self._q("DELETE FROM agent_sources WHERE strategy_id=?", (sid,))
        self._q("DELETE FROM runs WHERE strategy_id=?", (sid,))
        self._q("DELETE FROM versions WHERE strategy_id=?", (sid,))
        self._q("DELETE FROM strategies WHERE id=?", (sid,))

    # ----- versions -----
    def add_version(self, sid: str, body: dict, hash_: str) -> dict:
        row = self._q("SELECT COALESCE(MAX(number),0)+1 AS n FROM versions WHERE strategy_id=?", (sid,)).fetchone()
        vid = _id()
        self._q("INSERT INTO versions(id,strategy_id,number,body,hash,created_at) VALUES(?,?,?,?,?,?)",
                (vid, sid, row["n"], json.dumps(body), hash_, _now()))
        return self.get_version(vid)

    def get_version(self, vid: str) -> dict | None:
        r = self._q("SELECT * FROM versions WHERE id=?", (vid,)).fetchone()
        return {**dict(r), "body": json.loads(r["body"])} if r else None

    # ----- datasets -----
    def add_dataset(self, name: str, symbol: str | None, source_note: str | None,
                    bars: list[Bar], hash_: str, synthetic: bool = False) -> dict:
        did = _id()
        payload = json.dumps([[b.date, b.open, b.high, b.low, b.close, b.volume] for b in bars])
        self._q("""INSERT INTO datasets(id,name,symbol,source_note,rows,first_date,last_date,hash,bars,synthetic,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (did, name, symbol, source_note, len(bars), bars[0].date, bars[-1].date, hash_, payload,
                 int(synthetic), _now()))
        return self.get_dataset_meta(did)

    def list_datasets(self) -> list[dict]:
        rows = self._q("""SELECT id,name,symbol,source_note,rows,first_date,last_date,hash,synthetic,created_at
                          FROM datasets ORDER BY created_at DESC""").fetchall()
        return [dict(r) for r in rows]

    def get_dataset_meta(self, did: str) -> dict | None:
        r = self._q("""SELECT id,name,symbol,source_note,rows,first_date,last_date,hash,synthetic,created_at
                       FROM datasets WHERE id=?""", (did,)).fetchone()
        return dict(r) if r else None

    def get_bars(self, did: str) -> list[Bar] | None:
        r = self._q("SELECT bars FROM datasets WHERE id=?", (did,)).fetchone()
        return [Bar(*row) for row in json.loads(r["bars"])] if r else None

    def find_dataset_by_hash(self, hash_: str) -> dict | None:
        r = self._q("SELECT id FROM datasets WHERE hash=?", (hash_,)).fetchone()
        return self.get_dataset_meta(r["id"]) if r else None

    # ----- runs -----
    def add_run(self, sid: str, version_id: str | None, dataset_id: str, body: dict, result: dict) -> str:
        rid = _id()
        self._q("INSERT INTO runs(id,strategy_id,version_id,dataset_id,strategy_body,result,created_at) VALUES(?,?,?,?,?,?,?)",
                (rid, sid, version_id, dataset_id, json.dumps(body), json.dumps(result), _now()))
        return rid

    def list_runs(self, sid: str) -> list[dict]:
        rows = self._q("""SELECT r.id, r.version_id, r.dataset_id, r.created_at, r.result, d.name AS dataset_name,
                          v.number AS version_number
                          FROM runs r JOIN datasets d ON d.id = r.dataset_id
                          LEFT JOIN versions v ON v.id = r.version_id
                          WHERE r.strategy_id=? ORDER BY r.created_at DESC""", (sid,)).fetchall()
        out = []
        for r in rows:
            m = json.loads(r["result"])["metrics"]
            out.append({"id": r["id"], "version_id": r["version_id"], "version_number": r["version_number"],
                        "dataset_id": r["dataset_id"], "dataset_name": r["dataset_name"],
                        "created_at": r["created_at"], "total_return_pct": m["total_return_pct"],
                        "trades": m["trades"], "max_drawdown_pct": m["max_drawdown_pct"]})
        return out

    def get_run(self, rid: str) -> dict | None:
        r = self._q("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "strategy_id": r["strategy_id"], "version_id": r["version_id"],
                "dataset_id": r["dataset_id"], "created_at": r["created_at"],
                "strategy": json.loads(r["strategy_body"]), "result": json.loads(r["result"])}


    # ----- SuperAgent: AI decisions (cached so the model is never re-asked) and paper accounts -----
    def get_decisions(self, key: str) -> dict[str, dict]:
        rows = self._q("SELECT date, payload FROM agent_decisions WHERE cache_key=? ORDER BY date", (key,)).fetchall()
        return {r["date"]: json.loads(r["payload"]) for r in rows}

    def save_decision(self, key: str, date: str, payload: dict):
        self._q("INSERT OR REPLACE INTO agent_decisions(cache_key,date,payload,created_at) VALUES(?,?,?,?)",
                (key, date, json.dumps(payload), _now()))

    def add_paper(self, name: str, agent_id: str, dataset_id: str, symbol: str | None, synthetic: bool,
                  start_date: str, capital: float, analyses: list[str] | None = None) -> dict:
        pid = _id()
        self._q("""INSERT INTO paper_accounts(id,name,agent_id,dataset_id,symbol,synthetic,start_date,sim_days,capital,created_at,analyses)
                   VALUES(?,?,?,?,?,?,?,0,?,?,?)""",
                (pid, name, agent_id, dataset_id, symbol, int(synthetic), start_date, capital, _now(),
                 json.dumps(analyses or [])))
        return self.get_paper(pid)

    @staticmethod
    def _paper(r) -> dict:
        d = dict(r)
        d["analyses"] = json.loads(d["analyses"]) if d.get("analyses") else []
        return d

    def get_paper(self, pid: str) -> dict | None:
        r = self._q("SELECT * FROM paper_accounts WHERE id=?", (pid,)).fetchone()
        return self._paper(r) if r else None

    def list_paper(self) -> list[dict]:
        return [self._paper(r) for r in self._q("SELECT * FROM paper_accounts ORDER BY created_at DESC").fetchall()]

    def advance_paper(self, pid: str):
        self._q("UPDATE paper_accounts SET sim_days = sim_days + 1 WHERE id=?", (pid,))

    def delete_paper(self, pid: str):
        self._q("DELETE FROM agent_decisions WHERE cache_key=?", (f"paper:{pid}",))
        self._q("DELETE FROM paper_accounts WHERE id=?", (pid,))

    def latest_dataset_for(self, symbol: str) -> dict | None:
        r = self._q("SELECT id FROM datasets WHERE symbol=? AND synthetic=0 ORDER BY last_date DESC, created_at DESC LIMIT 1",
                    (symbol,)).fetchone()
        return self.get_dataset_meta(r["id"]) if r else None


def default_store() -> Store:
    path = os.environ.get("PURPLE_DB", str(Path(__file__).resolve().parents[1] / "data" / "purple.sqlite3"))
    return Store(path)
