import json
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from purple_api import desk, desk_routes, market, news
from purple_api.main import create_app
from purple_api.sample import synthetic_bars
from purple_api.store import Store

from test_api import FakeProvider


def bars30(n: int, seed_shift: float = 0.0, day0=datetime(2026, 9, 1)) -> list:
    """n synthetic 30-minute bars, 13 per weekday session from 09:15 IST."""
    base, out, d = synthetic_bars(n), [], day0
    while len(out) < n:
        if d.weekday() < 5:
            for k in range(desk.BARS_PER_DAY):
                if len(out) == n:
                    break
                b = base[len(out)]
                t = (d.replace(hour=9, minute=15) + timedelta(minutes=30 * k)).strftime("%Y-%m-%d %H:%M")
                out.append(replace(b, date=t, open=b.open + seed_shift, high=b.high + seed_shift,
                                   low=b.low + seed_shift, close=b.close + seed_shift))
        d += timedelta(days=1)
    return out


def panel(n=300):
    stocks = {s: bars30(n, i * 3.0) for i, s in enumerate(desk.UNIVERSE)}
    return desk.align(stocks, bars30(n))


def test_simulate_fills_next_open_and_charges_costs():
    p = panel(40)
    sim = desk.simulate(p, {5: {"RELIANCE.NS": 0.5}}, 100_000, start=0, notes={5: "momentum"})
    buy = sim["trades"][0]
    assert buy["time"] == p.times[6] and buy["side"] == "BUY" and buy["why"] == "momentum"
    assert buy["price"] == round(p.bars["RELIANCE.NS"][6].open * 1.0005, 2)
    assert 45_000 < buy["value"] <= 50_000 and len(sim["equity"]) == 40
    sim2 = desk.simulate(p, {5: {"RELIANCE.NS": 0.5}, 10: {}}, 100_000)
    assert [t["side"] for t in sim2["trades"]] == ["BUY", "SELL"] and not sim2["holdings"]


def test_every_agent_proposes_valid_weights_and_backtest_runs():
    p = panel()
    sh = desk.shadows(p, 500_000, moods={60: {"INFY.NS": 0.8, "TCS.NS": -0.5}})
    for a in desk.AGENT_IDS:
        for w in sh["agents"][a]["proposals"].values():
            assert sum(w.values()) <= 1.0 + 1e-9 and all(0 < x <= desk.MAX_WEIGHT for x in w.values())
    assert "TCS.NS" not in sh["agents"]["news"]["proposals"][100]
    bt = desk.backtest(p, 500_000, 5 * desk.BARS_PER_DAY)
    assert set(bt["winners"].values()) <= set(desk.AGENT_IDS) and bt["sim"]["equity"][0]["value"] == 500_000
    assert desk.weekly(p, bt["sim"], 5 * desk.BARS_PER_DAY, 500_000)


def test_parse_chief_validates_the_ai_answer():
    props = {"momentum": {"INFY.NS": 0.32}}
    got = desk.parse_chief('ok {"winner":"momentum","targets":{"infy":0.9,"XYZ":0.2,"TCS.NS":0.3},'
                           '"debate":[{"agent":"momentum","case":"strong"},{"agent":"hacker","case":"x"}],'
                           '"reason":"Buy IT.","confidence":70}', props)
    assert got["targets"] == {"INFY.NS": 0.35, "TCS.NS": 0.3} and [d["agent"] for d in got["debate"]] == ["momentum"]
    assert desk.parse_chief('{"winner":"momentum"}', props)["targets"] == {"INFY.NS": 0.32}
    with pytest.raises(ValueError):
        desk.parse_chief('{"winner":"nobody"}', props)


def test_next_bar_close():
    ist = market.IST
    assert desk_routes.next_bar_close(datetime(2026, 10, 22, 10, 0, tzinfo=ist)).strftime("%H:%M") == "10:15"
    assert desk_routes.next_bar_close(datetime(2026, 10, 22, 15, 40, tzinfo=ist)).strftime("%d %H:%M") == "22 15:45"
    assert desk_routes.next_bar_close(datetime(2026, 10, 22, 15, 50, tzinfo=ist)).strftime("%d %H:%M") == "23 09:45"
    assert desk_routes.next_bar_close(datetime(2026, 10, 24, 12, 0, tzinfo=ist)).strftime("%a %H:%M") == "Mon 09:45"


@pytest.fixture
def client(monkeypatch):
    feed = {s: bars30(300, i * 3.0) for i, s in enumerate(desk.UNIVERSE)}
    feed[desk.MARKET] = bars30(300)
    monkeypatch.setattr(market, "intraday_bars", lambda s, interval="30m", range_="1mo", now=None: feed[s])
    monkeypatch.setattr(news, "headlines", lambda *a, **k: {"items": [{"title": "Good quarter"}], "notes": []})

    def make(provider):
        return TestClient(create_app(store=Store(":memory:"), provider=provider))
    return make


def test_start_bot_ai_chief_decides_and_view(client):
    mood = json.dumps({"INFY": {"score": 0.7, "why": "deal win"}})
    chief = json.dumps({"debate": [{"agent": "trend", "case": "uptrend"}], "winner": "trend",
                        "targets": {"INFY": 0.3}, "reason": "Buy Infosys.", "confidence": 60})
    prov = FakeProvider(mood, chief)
    prov.name = "gemini"
    c = client(prov)
    assert c.get("/api/desk").json()["bot"] is None
    v = c.post("/api/desk", json={"capital": 500000, "days": 7}).json()
    assert v["bot"]["status"] == "running" and v["value"] == 500000
    c.post("/api/desk/decide")
    v = c.get("/api/desk").json()
    d = v["decisions"][0]
    assert d["winner"] == "trend" and d["targets"] == {"INFY": 0.3} and d["by"].startswith("gemini")
    assert v["mood"]["scores"]["INFY"]["score"] == 0.7 and len(v["agents"]) == 5
    assert "<data>" in prov.calls[0][-1]["content"]
    assert c.post("/api/desk/stop").json()["bot"]["status"] == "stopped"


def test_without_ai_the_track_record_decides(client):
    c = client(FakeProvider())  # name "fake": not a background AI
    c.post("/api/desk", json={"capital": 300000, "days": 0})
    c.post("/api/desk/decide")
    d = c.get("/api/desk").json()["decisions"][0]
    assert d["by"] == "record" and d["winner"] in desk.AGENT_IDS and "No AI answered" in d["reason"]


def test_backtest_endpoint(client):
    r = client(FakeProvider()).get("/api/desk/backtest?days=10").json()
    assert r["capital"] == 500000 and len(r["agents"]) == 5 and r["series"] and "weeks_beat" in r
