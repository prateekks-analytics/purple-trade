"""Deterministic daily backtest.

Timing contract (shown to users verbatim via describe()):
- Conditions are evaluated on each completed bar's close.
- A signal on bar t fills at the open of bar t+1. No signal on the last bar can fill.
- While holding: bars_held = completed bars since the fill bar (fill bar's close = 1);
  pnl_pct = (close / entry fill price - 1) * 100.
- Long only, whole shares, one position at a time. Open positions at the end are
  marked to the last close and reported as open, not force-sold.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Optional

from . import indicators
from .describe import condition_text, warmup_bars
from .schema import (
    All, AnyOf, Compare, ConstOperand, Cross, IndicatorOperand, Not,
    PositionOperand, PriceOperand, Strategy,
)

ENGINE_VERSION = "purple-engine/1.0"


@dataclass
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class _Pos:
    entry_index: int
    entry_price: float
    qty: int
    entry_fee: float
    entry_reason: str
    bars_held: int = 0
    pnl_pct: float = 0.0


@dataclass
class _Ctx:
    bars: list[Bar]
    cache: dict = field(default_factory=dict)
    pos: Optional[_Pos] = None


def _series(ctx: _Ctx, o) -> list[Optional[float]]:
    key = json.dumps(o.model_dump(), sort_keys=True)
    if key in ctx.cache:
        return ctx.cache[key]
    if isinstance(o, PriceOperand):
        base = [getattr(b, o.field) for b in ctx.bars]
        out = indicators.shift(base, o.offset)
    elif isinstance(o, IndicatorOperand):
        src = [getattr(b, o.source) for b in ctx.bars]
        out = indicators.shift(indicators.compute(o.name, src, o.period), o.offset)
    else:
        raise TypeError(o)
    ctx.cache[key] = out
    return out


def _value(ctx: _Ctx, o, t: int) -> Optional[float]:
    if t < 0:
        return None
    if isinstance(o, ConstOperand):
        return o.value
    if isinstance(o, PositionOperand):
        if ctx.pos is None:
            return None
        return float(ctx.pos.bars_held) if o.field == "bars_held" else ctx.pos.pnl_pct
    return _series(ctx, o)[t]


def _cmp(a: float, op: str, b: float) -> bool:
    if op in ("==", "!="):
        eq = round(a, 2) == round(b, 2)
        return eq if op == "==" else not eq
    return {"<": a < b, "<=": a <= b, ">=": a >= b, ">": a > b}[op]


def evaluate(ctx: _Ctx, c, t: int) -> bool:
    if isinstance(c, Compare):
        a, b = _value(ctx, c.left, t), _value(ctx, c.right, t)
        return a is not None and b is not None and _cmp(a, c.op, b)
    if isinstance(c, Cross):
        a, b = _value(ctx, c.left, t), _value(ctx, c.right, t)
        pa, pb = _value(ctx, c.left, t - 1), _value(ctx, c.right, t - 1)
        if None in (a, b, pa, pb):
            return False
        return (pa <= pb and a > b) if c.direction == "above" else (pa >= pb and a < b)
    if isinstance(c, All):
        return all(evaluate(ctx, i, t) for i in c.items)
    if isinstance(c, AnyOf):
        return any(evaluate(ctx, i, t) for i in c.items)
    if isinstance(c, Not):
        return not evaluate(ctx, c.item, t)
    raise TypeError(c)


def _reason(ctx: _Ctx, c, t: int) -> str:
    """Name the specific branches that fired, so every trade is explained."""
    if isinstance(c, AnyOf):
        fired = [condition_text(i) for i in c.items if evaluate(ctx, i, t)]
        return "; ".join(fired) or condition_text(c)
    return condition_text(c)


def _r(x: float, nd: int = 2) -> float:
    return round(x, nd)


def run_backtest(strategy: Strategy, bars: list[Bar], trade_from: int = 0) -> dict:
    """trade_from: first bar index whose close may raise a signal (earlier bars are warm-up only).
    Used by paper trading so an account starts flat on its start date."""
    if len(bars) < 2:
        raise ValueError("Need at least 2 bars.")
    ctx = _Ctx(bars=bars)
    fee = strategy.costs.fee_bps / 10_000
    slip = strategy.costs.slippage_bps / 10_000
    cash = strategy.initial_capital
    trades: list[dict] = []
    events: list[dict] = []
    equity: list[dict] = []
    pending: Optional[tuple[str, str]] = None  # ("buy"|"sell", reason)
    exposure_bars = 0

    for t, bar in enumerate(bars):
        # 1) fill orders from the previous close at this bar's open
        if pending:
            side, reason = pending
            pending = None
            if side == "buy" and ctx.pos is None:
                px = bar.open * (1 + slip)
                budget = cash * strategy.sizing.value / 100
                qty = math.floor(budget / (px * (1 + fee)))
                if qty < 1:
                    events.append({"date": bar.date, "type": "skipped",
                                   "detail": f"Not enough cash for 1 share at {px:.2f}"})
                else:
                    f = qty * px * fee
                    cash -= qty * px + f
                    ctx.pos = _Pos(t, px, qty, f, reason)
                    events.append({"date": bar.date, "type": "buy", "price": _r(px), "qty": qty})
            elif side == "sell" and ctx.pos is not None:
                p = ctx.pos
                px = bar.open * (1 - slip)
                f = p.qty * px * fee
                cash += p.qty * px - f
                cost = p.qty * p.entry_price + p.entry_fee
                pnl = p.qty * px - f - cost
                trades.append({
                    "entry_date": bars[p.entry_index].date, "entry_price": _r(p.entry_price),
                    "exit_date": bar.date, "exit_price": _r(px), "qty": p.qty,
                    "pnl": _r(pnl), "pnl_pct": _r(pnl / cost * 100),
                    "bars_held": p.bars_held, "entry_reason": p.entry_reason,
                    "exit_reason": reason, "fees": _r(p.entry_fee + f), "open": False,
                })
                events.append({"date": bar.date, "type": "sell", "price": _r(px), "qty": p.qty})
                ctx.pos = None

        # 2) update position state at this close
        if ctx.pos is not None:
            ctx.pos.bars_held = t - ctx.pos.entry_index + 1
            ctx.pos.pnl_pct = (bar.close / ctx.pos.entry_price - 1) * 100
            exposure_bars += 1

        # 3) evaluate rules on this close; schedule for next open
        if trade_from <= t < len(bars) - 1:
            if ctx.pos is None:
                if evaluate(ctx, strategy.entry, t):
                    pending = ("buy", _reason(ctx, strategy.entry, t))
            elif evaluate(ctx, strategy.exit, t):
                pending = ("sell", _reason(ctx, strategy.exit, t))

        held_value = ctx.pos.qty * bar.close if ctx.pos else 0.0
        equity.append({"date": bar.date, "equity": _r(cash + held_value), "close": bar.close})

    open_trade = None
    if ctx.pos is not None:
        p, last = ctx.pos, bars[-1]
        cost = p.qty * p.entry_price + p.entry_fee
        mtm = p.qty * last.close - cost
        open_trade = {
            "entry_date": bars[p.entry_index].date, "entry_price": _r(p.entry_price),
            "exit_date": None, "exit_price": None, "qty": p.qty, "pnl": _r(mtm),
            "pnl_pct": _r(mtm / cost * 100), "bars_held": p.bars_held,
            "entry_reason": p.entry_reason, "exit_reason": "Still open at last bar (marked to close)",
            "fees": _r(p.entry_fee), "open": True,
        }

    if trade_from:
        bars, equity = bars[trade_from:], equity[trade_from:]
    return {
        "engine": ENGINE_VERSION,
        "metrics": _metrics(strategy, bars, equity, trades, exposure_bars),
        "trades": trades + ([open_trade] if open_trade else []),
        "events": events,
        "equity": equity,
        "warmup_bars": warmup_bars(strategy),
        "strategy_hash": strategy_hash(strategy),
        "data_hash": bars_hash(bars),
    }


def _metrics(s: Strategy, bars, equity, trades, exposure_bars) -> dict:
    start, end = s.initial_capital, equity[-1]["equity"]
    peak, max_dd = start, 0.0
    for e in equity:
        peak = max(peak, e["equity"])
        max_dd = min(max_dd, e["equity"] / peak - 1)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in losses)
    from datetime import date
    days = (date.fromisoformat(bars[-1].date) - date.fromisoformat(bars[0].date)).days
    total = end / start - 1
    cagr = (end / start) ** (365.25 / days) - 1 if days > 0 and end > 0 else None
    bh = bars[-1].close / bars[0].open - 1
    return {
        "start_equity": _r(start), "end_equity": _r(end),
        "total_return_pct": _r(total * 100), "cagr_pct": _r(cagr * 100) if cagr is not None else None,
        "buy_hold_return_pct": _r(bh * 100), "max_drawdown_pct": _r(max_dd * 100),
        "trades": len(trades), "win_rate_pct": _r(len(wins) / len(trades) * 100) if trades else None,
        "avg_trade_pct": _r(sum(t["pnl_pct"] for t in trades) / len(trades)) if trades else None,
        "profit_factor": _r(gross_win / gross_loss) if gross_loss > 0 else None,
        "exposure_pct": _r(exposure_bars / len(bars) * 100),
        "fees_paid": _r(sum(t["fees"] for t in trades)),
        "bars": len(bars), "first_date": bars[0].date, "last_date": bars[-1].date,
    }


def strategy_hash(s: Strategy) -> str:
    payload = s.model_dump(exclude={"name", "questions"})
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def bars_hash(bars: list[Bar]) -> str:
    h = hashlib.sha256()
    for b in bars:
        h.update(f"{b.date},{b.open},{b.high},{b.low},{b.close},{b.volume}\n".encode())
    return h.hexdigest()[:16]
