import json
from datetime import date, timedelta

import pytest

from purple_api import bench, lab
from purple_api.engine import Bar

from test_lab import trend


def daily_rising(n=600, step=1.0):
    d0 = date(2008, 1, 1)
    return [Bar((d0 + timedelta(days=i)).isoformat(), 1000 + step * i - step / 2, 1000 + step * i + 2,
                1000 + step * i - step - 2, 1000 + step * i, 0) for i in range(n)]


@pytest.mark.parametrize("sig", list(bench.SIGNALS))
def test_every_signal_gives_positions(sig):
    pos = bench.raw_positions(sig, bench.SIGNALS[sig], lab.hourly(trend(600, 1.0)))
    assert set(pos) <= {-1, 0, 1} and len(pos) == len(lab.hourly(trend(600, 1.0)))


def test_side_and_regime_filters():
    h = lab.hourly(trend(400, -2.0))
    spec = {"signal": "supertrend"}
    assert -1 in bench.positions(spec, h, [])
    assert max(bench.positions({**spec, "side": "long"}, h, [])) <= 0
    assert set(bench.positions({**spec, "regime": "bull"}, h, [])) == {0}  # unknown regime: flat


def test_nearby_settings_change_one_number_at_a_time():
    near = bench.nearby({"n": 10, "mult": 3.0})
    assert {"n": 7, "mult": 3.0} in near and {"n": 14, "mult": 3.0} in near and {"n": 10, "mult": 4.2} in near
    assert all(isinstance(q["n"], int) for q in near)


def test_unknown_signal_is_refused():
    with pytest.raises(ValueError):
        bench.spec_params({"signal": "astrology"})


def test_trend_rule_in_a_steady_rise_is_judged_on_all_three_tests():
    res = bench.run({"name": "trend", "signal": "supertrend", "side": "long"}, lab.hourly(trend(600, 1.0)), daily_rising())
    assert res["verdict"] in ("strong", "weak", "fail") and len(res["why"]) == 3
    assert res["hourly"]["return_pct"] > 0 and res["daily"]["buy_hold"]["return_pct"] > 0
    assert "Bench: trend" in bench.markdown(res)


def test_day_trades_skip_the_daily_test_and_cap_at_weak():
    res = bench.run({"signal": "supertrend", "day_trade": True}, lab.hourly(trend(600, 1.0)), daily_rising())
    assert res["daily"] is None and res["verdict"] in ("weak", "fail")


def test_day_trade_account_is_flat_overnight():
    h = lab.hourly(trend(200, 1.0))
    sim = lab.simulate(h, [1] * len(h), h[0].date, 100_000, flat_eod=True)
    closes = [t for t in sim["trades"] if t["time"].endswith("close")]
    assert closes and all(t["to"] == 0 for t in closes) and sim["position"] == 0


def test_save_appends_without_the_nearby_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("PURPLE_COACH_DIR", str(tmp_path))
    res = bench.run({"signal": "ema_cross"}, lab.hourly(trend(600, 1.0)), daily_rising())
    bench.save(res)
    bench.save(res)
    rows = json.loads((tmp_path / "bench.json").read_text(encoding="utf-8"))
    assert len(rows) == 2 and "nearby" not in rows[0] and rows[0]["verdict"] == res["verdict"]
