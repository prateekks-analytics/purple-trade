"""Synthetic sample data (clearly labelled) and starter strategies."""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

from .engine import Bar


def synthetic_bars(n: int = 750, seed: int = 7, start: float = 1500.0) -> list[Bar]:
    rng = random.Random(seed)
    d = date(2023, 1, 2)
    px = start
    bars: list[Bar] = []
    regime_drift = 0.0004
    while len(bars) < n:
        if d.weekday() < 5:
            if len(bars) % 120 == 0:
                regime_drift = rng.choice([-0.0008, 0.0002, 0.0006, 0.0010])
            o = px * math.exp(rng.gauss(0, 0.004))
            c = o * math.exp(rng.gauss(regime_drift, 0.014))
            hi = max(o, c) * math.exp(abs(rng.gauss(0, 0.006)))
            lo = min(o, c) * math.exp(-abs(rng.gauss(0, 0.006)))
            vol = float(int(rng.uniform(4e5, 2e6)))
            bars.append(Bar(d.isoformat(), round(o, 2), round(hi, 2), round(lo, 2), round(c, 2), vol))
            px = c
        d += timedelta(days=1)
    return bars


def _ind(name, period):
    return {"kind": "indicator", "name": name, "period": period, "source": "close", "offset": 0}


_CLOSE = {"kind": "price", "field": "close", "offset": 0}


def _pos(field, op, value):
    return {"kind": "compare", "left": {"kind": "position", "field": field}, "op": op,
            "right": {"kind": "const", "value": value}}


TEMPLATES = [
    {
        "id": "trend", "title": "Trend follow", "blurb": "Buy when the close crosses above SMA(50); sell when it crosses back below.",
        "strategy": {"name": "SMA 50 trend",
                     "entry": {"kind": "cross", "left": _CLOSE, "direction": "above", "right": _ind("sma", 50)},
                     "exit": {"kind": "any", "items": [
                         {"kind": "cross", "left": _CLOSE, "direction": "below", "right": _ind("sma", 50)},
                         _pos("pnl_pct", "<=", -8)]}},
    },
    {
        "id": "dip", "title": "Buy the dip", "blurb": "Buy when RSI(14) crosses below 30; exit on RSI > 55, +5% or −3%.",
        "strategy": {"name": "RSI dip",
                     "entry": {"kind": "cross", "left": _ind("rsi", 14), "direction": "below", "right": {"kind": "const", "value": 30}},
                     "exit": {"kind": "any", "items": [
                         {"kind": "compare", "left": _ind("rsi", 14), "op": ">", "right": {"kind": "const", "value": 55}},
                         _pos("pnl_pct", ">=", 5), _pos("pnl_pct", "<=", -3)]}},
    },
    {
        "id": "breakout", "title": "20-day breakout", "blurb": "Buy when the close beats the previous 20-day high; hold up to 10 days or −4%.",
        "strategy": {"name": "20-day breakout",
                     "entry": {"kind": "compare", "left": _CLOSE, "op": ">",
                               "right": {"kind": "indicator", "name": "highest", "period": 20, "source": "high", "offset": 1}},
                     "exit": {"kind": "any", "items": [_pos("bars_held", ">=", 10), _pos("pnl_pct", "<=", -4)]}},
    },
]
