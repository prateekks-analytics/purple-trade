import math

import pytest

from purple_api import indicators
from purple_api.describe import describe, validate
from purple_api.engine import Bar, run_backtest
from purple_api.schema import Strategy


def bars_from_closes(closes, opens=None):
    opens = opens or closes
    return [Bar(f"2025-01-{i + 1:02d}", o, max(o, c), min(o, c), c, 1000) for i, (o, c) in enumerate(zip(opens, closes))]


def const(v):
    return {"kind": "const", "value": v}


CLOSE = {"kind": "price", "field": "close", "offset": 0}


def pos(field, op, v):
    return {"kind": "compare", "left": {"kind": "position", "field": field}, "op": op, "right": const(v)}


def strat(entry, exit_, **kw):
    return Strategy.model_validate({"entry": entry, "exit": exit_, "costs": {"fee_bps": 0, "slippage_bps": 0}, **kw})


# ---------- indicators ----------

def test_sma_values_and_warmup():
    assert indicators.sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_ema_seeded_with_sma():
    out = indicators.ema([1, 2, 3, 4], 3)
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(0.5 * 4 + 0.5 * 2.0)


def test_rsi_wilder_known_values():
    # 3 gains of +1 then a loss of -1, period 3
    out = indicators.rsi([10, 11, 12, 13, 12], 3)
    assert out[:3] == [None, None, None]
    assert out[3] == 100.0
    # avg_gain = (1*2 + 0)/3 = 2/3 ; avg_loss = (0*2 + 1)/3 = 1/3 ; RS = 2 -> 66.67
    assert out[4] == pytest.approx(100 - 100 / 3)


def test_highest_with_offset_is_previous_window():
    s = indicators.shift(indicators.rolling_extreme([1, 5, 2, 3], 2, True), 1)
    assert s == [None, None, 5, 5]


# ---------- engine timing ----------

def test_signal_on_close_fills_next_open():
    closes = [10, 10, 12, 12, 12]
    opens = [10, 10, 10, 13, 12]
    s = strat({"kind": "compare", "left": CLOSE, "op": ">", "right": const(11)}, pos("bars_held", ">=", 1))
    r = run_backtest(s, bars_from_closes(closes, opens))
    t = r["trades"][0]
    assert t["entry_date"] == "2025-01-04" and t["entry_price"] == 13  # close>11 on day 3, filled day 4 open
    assert t["exit_date"] == "2025-01-05"  # bars_held hits 1 at day-4 close, filled day-5 open


def test_sma20_two_day_or_1pct_exit_reports_which_rule_fired():
    closes = [100.0] * 20 + [95, 95.5, 96, 96.2, 96.4, 96.4]
    s = strat(
        {"kind": "cross", "left": CLOSE, "direction": "below",
         "right": {"kind": "indicator", "name": "sma", "period": 20, "source": "close", "offset": 0}},
        {"kind": "any", "items": [pos("bars_held", ">=", 2), pos("pnl_pct", ">=", 1), pos("pnl_pct", "<=", -1)]},
    )
    r = run_backtest(s, bars_from_closes(closes))
    t = r["trades"][0]
    # cross below on index 20 (close 95), fill index 21 open 95.5
    assert t["entry_price"] == 95.5
    # index 21 close 95.5 -> pnl 0, held 1 ; index 22 close 96 -> pnl +0.52%, held 2 -> time exit
    assert t["exit_reason"] == "Days held ≥ 2"
    assert t["bars_held"] == 2


def test_profit_target_fires_before_time_exit():
    closes = [100.0] * 20 + [95, 95.5, 97, 97, 97]
    s = strat(
        {"kind": "cross", "left": CLOSE, "direction": "below",
         "right": {"kind": "indicator", "name": "sma", "period": 20, "source": "close", "offset": 0}},
        {"kind": "any", "items": [pos("bars_held", ">=", 5), pos("pnl_pct", ">=", 1), pos("pnl_pct", "<=", -1)]},
    )
    t = run_backtest(s, bars_from_closes(closes))["trades"][0]
    assert t["exit_reason"] == "Trade P&L ≥ +1%"


def test_equality_uses_two_decimal_rounding_and_strict_greater():
    s = strat({"kind": "compare", "left": CLOSE, "op": "==", "right": const(10)},
              {"kind": "compare", "left": CLOSE, "op": ">", "right": const(12)})
    closes = [9, 10.004, 12, 12.01, 11]
    r = run_backtest(s, bars_from_closes(closes))
    t = r["trades"][0]
    assert t["entry_date"] == "2025-01-03"          # 10.004 rounds to 10.00
    assert t["exit_date"] == "2025-01-05"           # 12 is not > 12; 12.01 is


def test_no_lookahead_last_bar_signal_never_fills():
    s = strat({"kind": "compare", "left": CLOSE, "op": ">", "right": const(50)}, pos("bars_held", ">=", 1))
    r = run_backtest(s, bars_from_closes([10, 10, 10, 60]))
    assert r["trades"] == []


def test_costs_and_whole_shares():
    s = Strategy.model_validate({
        "entry": {"kind": "compare", "left": CLOSE, "op": ">", "right": const(0)},
        "exit": pos("bars_held", ">=", 1),
        "costs": {"fee_bps": 10, "slippage_bps": 0}, "initial_capital": 1000})
    r = run_backtest(s, bars_from_closes([100, 100, 100]))
    t = r["trades"][0]
    assert t["qty"] == 9                     # 1000 / (100 * 1.001) = 9.99 -> 9
    assert t["fees"] == pytest.approx(0.9 + 0.9)
    assert t["pnl"] == pytest.approx(-1.8)


def test_open_position_marked_to_market_not_sold():
    s = strat({"kind": "compare", "left": CLOSE, "op": ">", "right": const(0)}, pos("bars_held", ">=", 99))
    r = run_backtest(s, bars_from_closes([10, 10, 11]))
    assert r["trades"][-1]["open"] is True
    assert r["metrics"]["trades"] == 0


# ---------- validation & description ----------

def test_entry_cannot_use_position_operands():
    s = strat(pos("pnl_pct", ">", 1), pos("bars_held", ">=", 1))
    assert not validate(s)["ok"]


def test_questions_block_approval():
    s = strat({"kind": "compare", "left": CLOSE, "op": ">", "right": const(1)}, pos("bars_held", ">=", 1),
              questions=["Which period?"])
    v = validate(s)
    assert not v["ok"] and any("open question" in e for e in v["errors"])


def test_description_shows_exact_thresholds():
    rsi = {"kind": "indicator", "name": "rsi", "period": 14, "source": "close", "offset": 0}
    s = strat({"kind": "compare", "left": rsi, "op": "==", "right": const(10)},
              {"kind": "compare", "left": rsi, "op": ">", "right": const(90)})
    d = describe(s)
    assert d["entry"] == "RSI(14) = 10"
    assert d["exit"] == "RSI(14) > 90"
    assert any("rounding" in w for w in validate(s)["warnings"])


def test_rsi_threshold_out_of_range_rejected():
    rsi = {"kind": "indicator", "name": "rsi", "period": 14, "source": "close", "offset": 0}
    s = strat({"kind": "compare", "left": rsi, "op": "<", "right": const(150)}, pos("bars_held", ">=", 1))
    assert not validate(s)["ok"]
