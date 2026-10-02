"""Deterministic indicator series. Values are None until enough bars exist (warm-up)."""
from __future__ import annotations

from typing import Optional, Sequence

Series = list[Optional[float]]


def sma(values: Sequence[float], period: int) -> Series:
    out: Series = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= period:
            total -= values[i - period]
        if i >= period - 1:
            out[i] = total / period
    return out


def ema(values: Sequence[float], period: int) -> Series:
    """Seeded with the SMA of the first `period` values, then alpha = 2/(period+1)."""
    out: Series = [None] * len(values)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def rsi(values: Sequence[float], period: int) -> Series:
    """Wilder's RSI. First value appears at index `period`."""
    out: Series = [None] * len(values)
    if len(values) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def rolling_extreme(values: Sequence[float], period: int, highest: bool) -> Series:
    """Highest/lowest over the last `period` bars, including the current bar."""
    out: Series = [None] * len(values)
    pick = max if highest else min
    for i in range(period - 1, len(values)):
        out[i] = pick(values[i - period + 1 : i + 1])
    return out


def shift(series: Sequence[Optional[float]], offset: int) -> Series:
    if offset == 0:
        return list(series)
    return [None] * min(offset, len(series)) + list(series[: max(len(series) - offset, 0)])


def compute(name: str, values: Sequence[float], period: int) -> Series:
    if name == "sma":
        return sma(values, period)
    if name == "ema":
        return ema(values, period)
    if name == "rsi":
        return rsi(values, period)
    if name == "highest":
        return rolling_extreme(values, period, highest=True)
    if name == "lowest":
        return rolling_extreme(values, period, highest=False)
    raise ValueError(f"Unknown indicator {name!r}")
