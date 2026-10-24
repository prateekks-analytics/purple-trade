from datetime import date, timedelta

from purple_api import lab
from purple_api.engine import Bar

from test_desk import bars30


def trend(n, step, day0="2026-09-01"):
    """30-minute bars rising (step > 0) or falling (step < 0) steadily, with a small range."""
    out = []
    for i, b in enumerate(bars30(n)):
        c = 1000 + step * i
        out.append(Bar(b.date, c - step / 2, max(c, c - step / 2) + 1, min(c, c - step / 2) - 1, c, 0))
    return out


def test_hourly_pairs_halves_and_keeps_1515_alone():
    h = lab.hourly(bars30(13))  # one full day
    assert [b.date[11:] for b in h] == ["09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"]
    b30 = bars30(13)
    assert h[0].open == b30[0].open and h[0].close == b30[1].close
    assert h[0].high == max(b30[0].high, b30[1].high)


def test_hourly_leaves_out_an_hour_still_open():
    h = lab.hourly(bars30(14))  # second day: only 09:15 done
    assert h[-1].date.endswith("15:15")


def test_supertrend_follows_the_trend():
    assert lab.supertrend(lab.hourly(trend(300, 2.0)))[-1] == 1
    assert lab.supertrend(lab.hourly(trend(300, -2.0)))[-1] == -1
    assert lab.supertrend(lab.hourly(trend(300, 2.0)))[:30] == [0] * 30  # warm-up


def test_simulate_trades_next_open_and_pays_costs():
    hours = [Bar(f"2026-10-0{1 + i // 7} {9 + i % 7:02d}:15", 100.0, 100.0, 100.0, 100.0, 0) for i in range(14)]
    sim = lab.simulate(hours, [1] * 14, hours[0].date, 100_000)
    assert sim["trades"][0]["time"] == hours[1].date  # decided on hour 0's close, filled at hour 1's open
    assert sim["return_pct"] < 0 and len(sim["trades"]) == 1  # flat prices: only the buying cost
    short = lab.simulate(hours, [-1] * 14, hours[0].date, 100_000)
    assert short["position"] == -1


def test_short_gains_when_prices_fall():
    h = lab.hourly(trend(400, -2.0))
    sim = lab.simulate(h, lab.positions("trend_hourly", h, []), h[0].date, 100_000)
    assert sim["return_pct"] > 0


def test_bear_short_needs_nifty_below_its_200_day_average():
    h = lab.hourly(trend(400, -2.0))
    days = sorted({b.date[:10] for b in h})
    past = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(200)]
    rising = [Bar(d, 0, 0, 0, 100 + i, 0) for i, d in enumerate(past + days)]
    assert lab.positions("bear_short", h, rising) == [0] * len(h)  # NIFTY above its average: never short
    falling = [Bar(d, 0, 0, 0, 2000 - i, 0) for i, d in enumerate(past + days)]
    assert -1 in lab.positions("bear_short", h, falling)
    assert lab.positions("bear_short", h, []) == [0] * len(h)  # no daily history: flat


def test_assess_demotes_on_a_risk_breach_and_waits_on_returns():
    c = lab.CANDIDATES[0]
    medium = lab.RISK_LEVELS["medium"]
    calm = {"return_pct": -3.0, "max_drawdown_pct": -5.0, "trades": [{}] * 5}
    a = lab.assess(c, calm, 1.0, 10, "2026-11-05", medium)
    assert a["verdict"].startswith("Keep in shadow") and not a["flags"]  # behind NIFTY, but too early
    crash = {**calm, "max_drawdown_pct": -30.0}
    assert lab.assess(c, crash, 1.0, 10, "2026-11-05", medium)["verdict"].startswith("Demote now")


def test_promotion_is_blocked_by_the_risk_level():
    c = lab.CANDIDATES[0]
    good = {"return_pct": 8.0, "max_drawdown_pct": -4.0, "trades": [{}] * 20}
    med = lab.assess(c, good, 2.0, 60, "2027-01-27", lab.RISK_LEVELS["medium"])
    assert "risk level that allows futures" in med["verdict"] and med["blocked_by_risk_level"]
    high = lab.assess(c, good, 2.0, 60, "2027-01-27", lab.RISK_LEVELS["high"])
    assert "trial at 10%" in high["verdict"]
    assert 0 < high["live_weight"] < 0.5 and high["blended_edge_per_year_pct"] is not None


def test_risk_level_defaults_to_todays_bot(monkeypatch):
    monkeypatch.delenv("PURPLE_RISK_LEVEL", raising=False)
    assert lab.risk_level()["id"] == "medium" and not lab.risk_level()["shorts"]
    monkeypatch.setenv("PURPLE_RISK_LEVEL", "nonsense")
    assert lab.risk_level()["id"] == "medium"


def test_report_tracks_shadow_candidates_from_their_start(monkeypatch):
    b = trend(400, 1.0)  # 1 Sep to late Oct 2026
    since = b[200].date[:10]
    monkeypatch.setattr(lab, "CANDIDATES", [{**c, "since": since} for c in lab.CANDIDATES])
    rep = lab.report(b, [], today=b[-1].date[:10])
    assert rep["risk_level"]["id"] == "medium"
    rows = {r["id"]: r for r in rep["candidates"]}
    tr = rows["trend_hourly"]
    assert tr["paper"]["return_pct"] > 0 and tr["nifty_pct"] > 0 and tr["trades"] >= 1
    assert all(t["time"] >= since for t in tr["last_trades"])
    assert tr["assessment"]["verdict"].startswith("Keep in shadow")
    assert rows["bear_short"]["paper"]["position"] == 0  # no daily prices: stays flat
    assert "Strategy lab" in "\n".join(lab.markdown(rep))
