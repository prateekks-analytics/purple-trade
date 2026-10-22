import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from purple_api import challenge, market
from purple_api.main import create_app
from purple_api.sample import synthetic_bars
from purple_api.schema import Strategy
from purple_api.store import Store

from test_api import FakeProvider
from test_superagent import wait

PRICE = {"kind": "price", "field": "close", "offset": 0}
ALWAYS_IN = {"name": "Always in", "entry": {"kind": "compare", "left": PRICE, "op": ">", "right": {"kind": "const", "value": 0}},
             "exit": {"kind": "compare", "left": PRICE, "op": "<", "right": {"kind": "const", "value": 0}}}
NEVER_IN = {**ALWAYS_IN, "name": "Never in", "entry": {"kind": "compare", "left": PRICE, "op": "<", "right": {"kind": "const", "value": 0}}}


def flat_index(bars):
    return [replace(b, open=100.0, high=100.0, low=100.0, close=100.0) for b in bars]


def test_weekly_compares_each_week_with_the_market():
    bars = synthetic_bars(300)
    card = challenge.weekly(Strategy.model_validate(NEVER_IN), bars, flat_index(bars), weeks=10)
    assert len(card["weeks"]) == 10 and card["summary"]["beat"] == 0  # cash vs a flat market: never ahead
    assert all(w["bot_pct"] == 0 and not w["in_market"] for w in card["weeks"])
    assert card["weeks"][-1]["end"] == bars[-1].date
    a, b = card["weeks"][-2], card["weeks"][-1]
    assert a["end"] == b["start"]  # back-to-back weeks of WEEK sessions
    assert "cash" in card["summary"]["verdict"].lower()

    falling = [replace(b, close=100.0 - i * 0.1) for i, b in enumerate(flat_index(bars))]
    card = challenge.weekly(Strategy.model_validate(NEVER_IN), bars, falling, weeks=10)
    assert card["summary"]["beat"] == 10 == card["summary"]["cash_beat"]  # "wins" only because the market fell
    assert "only 'wins'" in card["summary"]["verdict"]


def test_split_keeps_the_newest_weeks_from_the_coach():
    bars = synthetic_bars(300)
    card = challenge.weekly(Strategy.model_validate(ALWAYS_IN), bars, flat_index(bars), weeks=20)
    learn, unseen = challenge.split(card)
    assert learn["weeks"] == 20 - challenge.HOLDOUT and unseen["weeks"] == challenge.HOLDOUT


@pytest.fixture
def client(monkeypatch):
    bars = synthetic_bars(400)
    monkeypatch.setattr(market, "daily_bars", lambda symbol, *a, **k: flat_index(bars) if symbol == "^NSEI" else bars)
    monkeypatch.setattr(market, "quote", lambda symbol, now=None: {"price": 100, "session_open": False, "time": None})

    def make(provider=None):
        return TestClient(create_app(store=Store(":memory:"), provider=provider))
    return make


def test_replay_endpoint_rule_bot_and_inline_rules(client):
    c = client()
    r = c.post("/api/challenge/replay", json={"agent_id": "ta-ema-momentum", "symbol": "INFY"}).json()
    assert r["symbol"] == "INFY.NS" and r["market"] == "NIFTY 50" and len(r["weeks"]) == challenge.WEEKS
    assert r["learn"]["weeks"] + r["unseen"]["weeks"] == challenge.WEEKS and r["describe"]["entry"]
    r = c.post("/api/challenge/replay", json={"strategy": ALWAYS_IN, "symbol": "INFY", "weeks": 6}).json()
    assert len(r["weeks"]) == 6 and all(w["in_market"] for w in r["weeks"])
    assert c.post("/api/challenge/replay", json={"agent_id": "purple-agent", "symbol": "INFY"}).status_code == 422


def test_coach_keeps_only_a_change_that_wins_more_weeks(client):
    better = {"strategy": ALWAYS_IN, "questions": [], "notes": "Stay invested."}
    worse = {"strategy": NEVER_IN, "questions": [], "notes": "Never buy."}
    prov = FakeProvider(json.dumps(worse), json.dumps(better), json.dumps(worse))
    c = client(prov)
    base = c.post("/api/challenge/replay", json={"strategy": NEVER_IN, "symbol": "INFY"}).json()
    j = c.post("/api/challenge/coach", json={"strategy": NEVER_IN, "symbol": "INFY", "hint": "trade more"}).json()["job"]
    res = wait(c, j["id"])["result"]
    assert len(res["tries"]) == 3 and len(prov.calls) == 3
    assert "trade more" in prov.calls[0][-1]["content"] and "Already tried" in prov.calls[2][-1]["content"]
    if res["after"]:  # the synthetic stock rose in more weeks than a flat index: staying in wins
        assert res["after"]["learn"]["beat"] > base["learn"]["beat"]
        assert res["after"]["strategy"]["name"] == "Always in"


def test_keep_then_race_against_the_market(client):
    c = client()
    k = c.post("/api/challenge/keep", json={"strategy": ALWAYS_IN, "name": "My week bot"}).json()
    assert k["agent_id"].startswith("version:") and k["title"] == "My week bot (version 1)"
    race = c.post("/api/challenge/races", json={"agent_id": k["agent_id"], "symbol": "INFY"}).json()
    assert race["days"] == challenge.WEEK and race["day"] == 0 and race["edge"] == 0
    assert race["market_value"] == race["bot_value"] == 100_000
    assert [r["id"] for r in c.get("/api/challenge/races").json()] == [race["id"]]
    assert c.get(f"/api/challenge/races/{race['id']}?live=1").json()["id"] == race["id"]
    plain = c.post("/api/superagent/paper", json={"agent_id": "ta-ema-momentum", "symbol": "INFY"}).json()
    assert c.get(f"/api/challenge/races/{plain['account']['id']}").status_code == 404
    assert c.post("/api/challenge/races", json={"agent_id": "purple-agent", "symbol": "INFY"}).status_code == 422
