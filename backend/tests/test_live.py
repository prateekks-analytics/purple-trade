import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from purple_api import live_agents, market, news
from purple_api.main import create_app
from purple_api.sample import synthetic_bars
from purple_api.store import Store

from test_superagent import TeamProvider, wait

UTC = timezone.utc


def intraday(n: int, day0=date(2026, 10, 12)) -> list:
    """n synthetic 5-minute bars, 75 per session from 09:15 IST, weekdays only."""
    out, d, i = [], day0, 0
    base = synthetic_bars(n)
    while i < n:
        if d.weekday() < 5:
            for k in range(75):
                if i == n:
                    break
                t = datetime(d.year, d.month, d.day, 9, 15) + timedelta(minutes=5 * k)
                out.append(replace(base[i], date=t.strftime("%Y-%m-%d %H:%M")))
                i += 1
        d += timedelta(days=1)
    return out


@pytest.fixture
def live(monkeypatch):
    daily = synthetic_bars(400)
    feed = {"daily": daily, "intra": intraday(300)}
    monkeypatch.setattr(market, "daily_bars", lambda symbol, *a, **k: feed["daily"])
    monkeypatch.setattr(market, "intraday_bars", lambda symbol, interval="5m", range_="1mo", now=None: feed["intra"])
    monkeypatch.setattr(market, "quote", lambda symbol, now=None: {"name": "Infosys Limited", "price": 1}, raising=True)
    seen = []

    def fake_headlines(name, ticker, sources, upto=None, limit=25, now=None):
        seen.append((name, ticker, tuple(sources), upto))
        return {"items": [{"source": "google", "title": "Infosys wins a large deal", "link": "",
                           "published": upto - timedelta(hours=3), "publisher": "Example News"}], "notes": []}
    monkeypatch.setattr(news, "headlines", fake_headlines)
    monkeypatch.setattr(market, "fundamentals", lambda symbol: [
        {"type": "DilutedEPS", "as_of": "2020-03-31", "value": 40.0, "currency": "INR"}])
    return feed, seen


# ---------- news feeds ----------

GOOGLE = """<?xml version="1.0"?><rss><channel>
<item><title>Infosys Q2 profit rises - Mint</title><link>https://x/1</link><pubDate>Tue, 13 Oct 2026 08:00:00 GMT</pubDate><source>Mint</source></item>
<item><title>Infosys Q2 profit rises - Mint</title><link>https://x/2</link><pubDate>Tue, 13 Oct 2026 07:00:00 GMT</pubDate></item>
<item><title>Future story</title><link>https://x/3</link><pubDate>Fri, 16 Oct 2026 08:00:00 GMT</pubDate></item>
</channel></rss>"""
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>INFY looks strong, buying more</title><link href="https://reddit/1"/><updated>2026-10-14T10:00:00+00:00</updated>
<category term="IndianStreetBets" label="r/IndianStreetBets"/></entry></feed>"""


def test_headlines_merge_dedupe_and_never_see_the_future(monkeypatch):
    news._cache.clear()
    monkeypatch.setattr(news, "_get", lambda url, params: ATOM if "reddit" in url else GOOGLE)
    now = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
    r = news.headlines("Infosys Limited", "INFY.NS", ["google", "reddit"], now=now)
    titles = [i["title"] for i in r["items"]]
    assert titles == ["INFY looks strong, buying more", "Infosys Q2 profit rises - Mint"]  # newest first, deduped
    assert "Future story" not in titles and r["notes"] == []
    assert "r/IndianStreetBets" in news.digest(r["items"], now)

    old = news.headlines("Infosys Limited", "INFY.NS", ["google", "reddit"], upto=datetime(2026, 10, 13, 9, 0, tzinfo=UTC),
                         now=now + timedelta(days=10))
    assert [i["title"] for i in old["items"]] == ["Infosys Q2 profit rises - Mint"]
    assert "only recent posts" in old["notes"][0]


def test_failing_source_is_a_note_not_an_error(monkeypatch):
    news._cache.clear()

    def boom(url, params):
        raise news.NewsError("HTTP 403")
    monkeypatch.setattr(news, "_get", boom)
    r = news.headlines("Infosys", "INFY.NS", ["google"])
    assert r["items"] == [] and "HTTP 403" in r["notes"][0]


def test_annual_figures_wait_for_the_filing_lag():
    rows = [{"type": "DilutedEPS", "as_of": "2026-03-31", "value": 60.0, "currency": "INR"},
            {"type": "DilutedEPS", "as_of": "2025-03-31", "value": 55.0, "currency": "INR"}]
    early = live_agents.fundamentals_text(rows, datetime(2026, 4, 20, tzinfo=market.IST))
    assert "2025-03-31" in early and "2026-03-31" not in early
    assert "2026-03-31" in live_agents.fundamentals_text(rows, datetime(2026, 6, 15, tzinfo=market.IST))


# ---------- news agents ----------

def test_news_pulse_backtest_reads_news_up_to_each_close(live):
    feed, seen = live
    p = TeamProvider(actions=("BUY", "HOLD", "SELL"))
    c = TestClient(create_app(store=Store(":memory:"), provider=p))
    r = c.post("/api/superagent/run", json={"agent_id": "news-pulse", "symbol": "infy", "days": 3,
                                             "analyses": ["google", "reddit"]})
    assert r.status_code == 200, r.text
    j = wait(c, r.json()["job"]["id"])
    assert j["status"] == "done", j["error"]
    assert [d["action"] for d in j["result"]["decisions"]] == ["BUY", "HOLD", "SELL"] and p.calls == 3
    assert [s[3] for s in seen] == [live_agents.bar_time(b.date) for b in feed["daily"][-3:]]
    assert seen[0][:3] == ("Infosys Limited", "INFY.NS", ("google", "reddit"))
    assert any(l["kind"] == "news" for l in j["log"])


def test_crew_makes_three_calls_per_decision(live):
    p = TeamProvider(actions=("HOLD",))
    c = TestClient(create_app(store=Store(":memory:"), provider=p))
    r = c.post("/api/superagent/run", json={"agent_id": "crew-nse", "symbol": "INFY", "days": 2, "analyses": ["google"]})
    j = wait(c, r.json()["job"]["id"])
    assert j["status"] == "done", j["error"]
    assert p.calls == 6 and {"research", "financial", "manager"} <= {l["kind"] for l in j["log"]}
    assert "DilutedEPS 40.00" in j["result"]["decisions"][0]["report"]


def test_ai_agents_limit_bar_sizes(live):
    c = TestClient(create_app(store=Store(":memory:"), provider=TeamProvider()))
    r = c.post("/api/superagent/paper", json={"agent_id": "crew-nse", "symbol": "INFY", "interval": "5m", "analyses": ["google"]})
    assert r.status_code == 422 and "1d, 30m" in r.json()["detail"]


# ---------- intraday paper accounts and the live loop ----------

def test_intraday_rule_account_moves_with_the_live_loop(live):
    feed, _ = live
    app = create_app(store=Store(":memory:"), provider=TeamProvider())
    c = TestClient(app)
    r = c.post("/api/superagent/paper", json={"agent_id": "ta-golden-cross", "symbol": "INFY", "interval": "5m"})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["interval"] == "5m" and v["account"]["name"].endswith("· 5m")
    assert v["latest_date"] == feed["intra"][-1].date == v["account"]["start_date"]
    assert "5m bars" in v["data_note"]

    feed["intra"] = intraday(310)  # ten more finished bars
    session = datetime(2026, 10, 16, 11, 0, tzinfo=market.IST)
    assert app.state.live_tick(session)["session"] == "open"
    v2 = c.get(f"/api/superagent/paper/{v['account']['id']}").json()
    assert v2["latest_date"] == feed["intra"][-1].date and v2["result"]["metrics"]["bars"] == 11
    st = c.get("/api/market/status").json()
    assert st["loop"]["bars_saved"] >= 10 and st["loop"]["intraday_accounts"] == 1
    assert app.state.live_tick(datetime(2026, 10, 17, 11, 0, tzinfo=market.IST))["session"] == "closed"  # Saturday


def test_live_loop_lets_free_server_ai_decide_news_accounts(live):
    p = TeamProvider(actions=("BUY",))
    p.name = "gemini"  # the loop only uses the server's own free AI
    app = create_app(store=Store(":memory:"), provider=p)
    c = TestClient(app)
    acct = c.post("/api/superagent/paper", json={"agent_id": "news-pulse", "symbol": "INFY", "analyses": ["google"]}).json()
    assert acct["pending_days"] == [acct["latest_date"]]
    app.state.live_tick(datetime(2026, 10, 15, 3, 0, tzinfo=UTC))
    v = c.get(f"/api/superagent/paper/{acct['account']['id']}").json()
    assert v["pending_days"] == [] and v["today"]["action"] == "BUY" and p.calls == 1


def test_rate_limit_pauses_yahoo_and_shows_in_status(monkeypatch):
    monkeypatch.setitem(market._state, "paused_until", 0.0)

    def limited(url, params):
        raise market.RateLimited("Yahoo Finance is limiting requests.")
    monkeypatch.setattr(market, "_fetch", limited)
    with pytest.raises(market.RateLimited):
        market.quote("INFY")
    st = market.status()
    assert st["rate_limited"] and 0 < st["retry_in_s"] <= market.PAUSE_S
    with pytest.raises(market.RateLimited, match="retries in"):  # paused: Yahoo is not called again
        market.quote("INFY")
    c = TestClient(create_app(store=Store(":memory:"), provider=TeamProvider()))
    assert c.get("/api/market/status").json()["rate_limited"]
    market._state["paused_until"] = 0.0
