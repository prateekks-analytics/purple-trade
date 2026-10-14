from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from purple_api import market
from purple_api.main import create_app
from purple_api.sample import synthetic_bars
from purple_api.store import Store

from test_superagent import TeamProvider

# 13, 14 and 15 Oct 2026, 09:35 IST (Yahoo stamps daily NSE bars during the session)
T13, T14, T15 = 1791864300, 1791950700, 1792037100


def _chart(timestamps, closes, meta=None):
    n = len(timestamps)
    return {"chart": {"result": [{"meta": meta or {}, "timestamp": timestamps, "indicators": {"quote": [{
        "open": [(c or 100) - 1 for c in closes], "high": [(c or 100) + 2 for c in closes],
        "low": [(c or 100) - 2 for c in closes], "close": closes, "volume": [1000] * n}]}}], "error": None}}


def test_ticker_defaults_to_nse():
    assert market.ticker(" reliance ") == "RELIANCE.NS"
    assert market.ticker("tcs.bo") == "TCS.BO" and market.ticker("^NSEI") == "^NSEI"
    with pytest.raises(market.MarketError):
        market.ticker("  ")


def test_daily_bars_keep_only_completed_sessions(monkeypatch):
    monkeypatch.setattr(market, "_fetch", lambda url, params: _chart([T13, T14, T15], [100.004, None, 102.5]))
    noon = datetime(2026, 10, 15, 6, 30, tzinfo=timezone.utc)  # 12:00 IST: today's bar is still forming
    with pytest.raises(market.MarketError):  # one completed bar (14 Oct has no close) is too few
        market.daily_bars("RELIANCE", now=noon)

    monkeypatch.setattr(market, "_fetch", lambda url, params: _chart([T13, T14, T15], [100.004, 101, 102.5]))
    bars = market.daily_bars("RELIANCE", now=noon)
    assert [b.date for b in bars] == ["2026-10-13", "2026-10-14"] and bars[0].close == 100.0
    evening = datetime(2026, 10, 15, 11, 0, tzinfo=timezone.utc)  # 16:30 IST: today's close counts
    assert market.daily_bars("RELIANCE", now=evening)[-1].date == "2026-10-15"

    # newest close left blank by Yahoo: taken from the last trade when it is on the same day
    meta = {"regularMarketPrice": 103.456, "regularMarketTime": T15 + 21000}
    monkeypatch.setattr(market, "_fetch", lambda url, params: _chart([T13, T14, T15], [100, 101, None], meta))
    assert market.daily_bars("RELIANCE", now=evening)[-1].close == 103.46
    assert market.daily_bars("RELIANCE", now=noon)[-1].date == "2026-10-14"


def test_quote_reports_session_state(monkeypatch):
    meta = {"regularMarketPrice": 1174.6, "chartPreviousClose": 1178.0, "currency": "INR", "regularMarketTime": T15 + 3600,
            "currentTradingPeriod": {"regular": {"start": T15, "end": T15 + 22500}}}
    monkeypatch.setattr(market, "_fetch", lambda url, params: _chart([], [], meta))
    q = market.quote("RELIANCE", now=datetime.fromtimestamp(T15 + 3600, timezone.utc))
    assert q["ticker"] == "RELIANCE.NS" and q["price"] == 1174.6 and q["session_open"]
    assert q["change_pct"] == -0.29 and q["time"].startswith("2026-10-15T10:35")
    assert not market.quote("RELIANCE", now=datetime.fromtimestamp(T15 + 30000, timezone.utc))["session_open"]


def test_live_paper_account_moves_forward_on_new_sessions(monkeypatch):
    bars = synthetic_bars(400)
    feed = {"n": 397}
    monkeypatch.setattr(market, "daily_bars", lambda symbol, *a, **k: bars[:feed["n"]])
    c = TestClient(create_app(store=Store(":memory:"), provider=TeamProvider()))

    r = c.post("/api/superagent/paper", json={"agent_id": "ta-golden-cross", "symbol": "reliance", "capital": 50000})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["account"]["symbol"] == "RELIANCE.NS" and v["can_refresh"] and not v["account"]["synthetic"]
    assert v["account"]["start_date"] == bars[396].date == v["latest_date"]
    assert "Yahoo Finance" in v["data_note"]

    feed["n"] = 400  # three more sessions closed
    v2 = c.post(f"/api/superagent/paper/{v['account']['id']}/refresh").json()
    assert v2["latest_date"] == bars[399].date and v2["account"]["start_date"] == bars[396].date
    assert v2["result"]["metrics"]["bars"] == 4
    assert c.post(f"/api/superagent/paper/{v['account']['id']}/refresh").json()["latest_date"] == bars[399].date
    assert sum(d["symbol"] == "RELIANCE.NS" for d in c.get("/api/datasets").json()) == 2  # same prices not stored twice


def test_market_endpoints_report_yahoo_errors(monkeypatch):
    def down(*a, **k):
        raise market.MarketError("Yahoo Finance can't be reached (ConnectError).")
    monkeypatch.setattr(market, "daily_bars", down)
    monkeypatch.setattr(market, "quote", down)
    c = TestClient(create_app(store=Store(":memory:"), provider=TeamProvider()))
    r = c.post("/api/market/prices", json={"symbol": "INFY"})
    assert r.status_code == 502 and "can't be reached" in r.json()["detail"]
    assert c.get("/api/market/quote", params={"symbol": "INFY"}).status_code == 502
