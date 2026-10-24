from datetime import datetime, timedelta

from purple_api import coach, desk, market, preopen
from purple_api.store import Store

from test_api import FakeProvider
from test_desk import client, seeded_bot  # noqa: F401 - fixture


def fake_quotes(changes):
    def get(sym):
        if changes.get(sym) is None:
            raise market.MarketError("no such symbol")
        return {"change_pct": changes[sym], "time": "2026-10-26T09:05:00+05:30"}
    return get


def test_read_counts_warning_signs():
    calm = preopen.read(datetime(2026, 10, 26, 9, 5, tzinfo=market.IST),
                        fake_quotes({"^GSPC": 0.4, "^N225": -0.5, "^HSI": 0.1, "^INDIAVIX": 1.0, "^NSEI": -0.2}))
    assert calm["signs"] == 0 and not calm["flagged"] and calm["at"][11:16] == "09:05"
    bad = preopen.read(None, fake_quotes({"^GSPC": -1.2, "^N225": -1.6, "^HSI": -1.0, "^INDIAVIX": 6.0, "^NSEI": None}))
    assert bad["signs"] == 3 and bad["flagged"]
    nifty = next(c for c in bad["cues"] if c["symbol"] == "^NSEI")
    assert nifty["change_pct"] is None and not nifty["sign"]  # Yahoo failed: no sign, still listed


def test_window_is_before_the_open_on_weekdays():
    mon = datetime(2026, 10, 26, tzinfo=market.IST)
    assert preopen.in_window(mon.replace(hour=9, minute=0)) and preopen.in_window(mon.replace(hour=9, minute=14))
    assert not preopen.in_window(mon.replace(hour=9, minute=15)) and not preopen.in_window(mon.replace(hour=8, minute=59))
    assert not preopen.in_window((mon - timedelta(days=1)).replace(hour=9, minute=5))  # Sunday


def test_held_before_counts_shares_going_into_the_day():
    trades = [{"time": "2026-10-22 09:45", "symbol": "INFY", "side": "BUY", "qty": 10},
              {"time": "2026-10-23 10:15", "symbol": "INFY", "side": "SELL", "qty": 4},
              {"time": "2026-10-26 09:45", "symbol": "TCS", "side": "BUY", "qty": 5},
              {"time": "now", "symbol": "SBIN", "side": "BUY", "qty": 3}]
    assert preopen.held_before(trades, "2026-10-26") == {"INFY": 6}


def test_day_test_sells_half_at_the_open_and_buys_back_at_the_close():
    db = Store(":memory:")
    p, bot = seeded_bot(db)
    day = p.times[200][:10]
    idx = [i for i, t in enumerate(p.times) if t.startswith(day)]
    trades = [{"time": p.times[idx[0] - 5], "symbol": "INFY", "side": "BUY", "qty": 100}]
    r = {"signs": 2, "flagged": True, "at": f"{day}T09:05", "cues": []}
    t = preopen.test_day(r, trades, p.times, p.bars, p.market, day, 500_000)
    o, c = p.bars["INFY.NS"][idx[0]].open, p.bars["INFY.NS"][idx[-1]].close
    assert t["flagged"] and t["sold_value"] == round(50 * o)
    assert t["extra_rupees"] < round(50 * (o - c)) + 1  # charges always cost something
    assert t["nifty_open_to_close_pct"] == round((p.market[idx[-1]].close / p.market[idx[0]].open - 1) * 100, 2)
    assert "Pre-open test" in "\n".join(preopen.markdown(t))
    assert preopen.test_day(None, trades, p.times, p.bars, p.market, "1999-01-01", 500_000) is None


def test_live_loop_reads_once_before_the_open_and_the_review_shows_it(client, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setenv("PURPLE_COACH_DIR", str(tmp_path))
    c = client(FakeProvider())
    c.post("/api/desk", json={"capital": 500000, "days": 0})
    db = c.app.state.store
    bot = db.list_desks()[0]
    calls = []

    def get(sym):
        calls.append(sym)
        return {"change_pct": -2.0, "time": "x"}
    monkeypatch.setattr(market, "quote", get)
    monkeypatch.setattr(preopen.market, "quote", get)
    p = coach.load_panel(db)
    last = datetime.strptime(p.times[-1], "%Y-%m-%d %H:%M")
    mon = last + timedelta(days=1)
    while mon.weekday() >= 5:
        mon += timedelta(days=1)
    now = mon.replace(hour=9, minute=5, tzinfo=market.IST)
    monkeypatch.setattr(preopen, "read", lambda now=None, get=get: {
        "at": now.isoformat(), "cues": [], "signs": len([get(s) for s, _, _ in preopen.CUES]), "flagged": True})
    c.app.state.desk_tick(now)
    c.app.state.desk_tick(now + timedelta(minutes=1))
    stored = db.get_decisions(f"deskpreopen:{bot['id']}")
    assert list(stored) == [mon.date().isoformat()] and stored[mon.date().isoformat()]["flagged"]
    assert len(calls) == len(preopen.CUES)  # read once a day, not every minute
    pack = coach.build_review(db, bot, p.times[-1][:10], p)
    assert pack["preopen_test"] is None or "nifty_open_to_close_pct" in pack["preopen_test"]
