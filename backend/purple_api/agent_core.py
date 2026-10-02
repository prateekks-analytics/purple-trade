"""AI analyst team: the decision core used by Trading SuperAgent.

Workflow modelled on TradingAgents (Tauric Research, Apache-2.0,
https://github.com/TauricResearch/TradingAgents): a market analyst writes a report, a bull and a bear
researcher debate it, and a trader / risk manager makes the call. This is Purple's own
re-implementation with paraphrased prompts, not TradingAgents' code.

The market report is computed deterministically from price bars (no AI, no look-ahead: only bars up
to and including the decision day are used). The indicator set and readings follow the guide in
TradingAgents' market analyst (SMA 50/200, EMA 10, MACD, RSI 70/30, Bollinger, ATR, VWMA).

This module is self-contained (stdlib + indicators) because the code export embeds it verbatim.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional, Sequence

from .indicators import ema, rsi, sma

ACTIONS = ("BUY", "SELL", "HOLD")


# ---------- extra indicators (report only) ----------

def macd(values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9):
    f, s = ema(values, fast), ema(values, slow)
    line = [a - b if a is not None and b is not None else None for a, b in zip(f, s)]
    first = next((i for i, v in enumerate(line) if v is not None), None)
    sig: list = [None] * len(values)
    if first is not None:
        tail = ema([v for v in line[first:]], signal)
        sig[first:] = tail
    hist = [a - b if a is not None and b is not None else None for a, b in zip(line, sig)]
    return line, sig, hist


def bollinger(values: Sequence[float], period: int = 20, k: float = 2.0):
    mid = sma(values, period)
    up: list = [None] * len(values)
    lo: list = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1: i + 1]
        m = mid[i]
        sd = (sum((x - m) ** 2 for x in window) / period) ** 0.5
        up[i], lo[i] = m + k * sd, m - k * sd
    return mid, up, lo


def atr(high: Sequence[float], low: Sequence[float], close: Sequence[float], period: int = 14):
    tr = [high[0] - low[0]] + [max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
                               for i in range(1, len(close))]
    out: list = [None] * len(close)
    if len(tr) < period:
        return out
    prev = sum(tr[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(tr)):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def vwma(close: Sequence[float], volume: Sequence[float], period: int = 20):
    out: list = [None] * len(close)
    for i in range(period - 1, len(close)):
        v = sum(volume[i - period + 1: i + 1])
        if v > 0:
            out[i] = sum(c * w for c, w in zip(close[i - period + 1: i + 1], volume[i - period + 1: i + 1])) / v
    return out


# ---------- market analyst (deterministic) ----------

def _f(x: Optional[float]) -> str:
    return "n/a (not enough history)" if x is None else f"{x:,.2f}"


def _crossed(a: Sequence, b: Sequence, t: int, lookback: int) -> Optional[str]:
    """'above'/'below' if series a crossed b within the last `lookback` bars up to t."""
    for i in range(t, max(t - lookback, 0), -1):
        if None in (a[i], b[i], a[i - 1], b[i - 1]):
            return None
        if a[i - 1] <= b[i - 1] and a[i] > b[i]:
            return f"above {t - i} day(s) ago" if i != t else "above today"
        if a[i - 1] >= b[i - 1] and a[i] < b[i]:
            return f"below {t - i} day(s) ago" if i != t else "below today"
    return None


def market_snapshot(bars: Sequence, t: int) -> dict:
    """Indicator readings on bar t's close, using bars[0..t] only."""
    b = bars[: t + 1]
    close = [x.close for x in b]
    high = [x.high for x in b]
    low = [x.low for x in b]
    vol = [x.volume for x in b]
    s50, s200, e10 = sma(close, 50), sma(close, 200), ema(close, 10)
    m, sig, hist = macd(close)
    r = rsi(close, 14)
    mid, up, lo = bollinger(close)
    a = atr(high, low, close)
    vw, s20 = vwma(close, vol), sma(close, 20)

    def chg(n):
        return (close[t] / close[t - n] - 1) * 100 if t >= n else None

    return {
        "date": b[t].date, "close": close[t], "sma50": s50[t], "sma200": s200[t], "ema10": e10[t],
        "macd": m[t], "macd_signal": sig[t], "macd_hist": hist[t], "rsi14": r[t],
        "boll_mid": mid[t], "boll_up": up[t], "boll_low": lo[t], "atr14": a[t], "vwma20": vw[t], "sma20": s20[t],
        "chg5_pct": chg(5), "chg20_pct": chg(20),
        "sma50_vs_200_cross": _crossed(s50, s200, t, 10),
        "macd_vs_signal_cross": _crossed(m, sig, t, 3),
        "close_vs_ema10_cross": _crossed(close, e10, t, 3),
    }


def market_report(symbol: str, s: dict) -> str:
    c = s["close"]
    lines = [f"Market report for {symbol} on {s['date']} (daily bars, readings on this close).",
             f"- Close {_f(c)}. 5-day change {_f(s['chg5_pct'])}%, 20-day change {_f(s['chg20_pct'])}%."]
    if s["sma50"] is not None:
        lines.append(f"- SMA50 {_f(s['sma50'])}: close is {'above' if c > s['sma50'] else 'below'} it (medium-term trend).")
    if s["sma200"] is not None and s["sma50"] is not None:
        regime = "golden-cross regime (SMA50 above SMA200)" if s["sma50"] > s["sma200"] else "death-cross regime (SMA50 below SMA200)"
        x = f"; SMA50 crossed {s['sma50_vs_200_cross']}" if s["sma50_vs_200_cross"] else ""
        lines.append(f"- SMA200 {_f(s['sma200'])}: {regime}{x}.")
    else:
        lines.append("- SMA200: n/a (needs 200 days of history).")
    if s["ema10"] is not None:
        x = f"; close crossed EMA10 {s['close_vs_ema10_cross']}" if s["close_vs_ema10_cross"] else ""
        lines.append(f"- EMA10 {_f(s['ema10'])}: close is {'above' if c > s['ema10'] else 'below'} it (short-term momentum){x}.")
    if s["macd"] is not None and s["macd_signal"] is not None:
        x = f"; MACD crossed its signal {s['macd_vs_signal_cross']}" if s["macd_vs_signal_cross"] else ""
        lines.append(f"- MACD {s['macd']:.2f} vs signal {s['macd_signal']:.2f} (histogram {s['macd_hist']:+.2f}): "
                     f"{'bullish' if s['macd'] > s['macd_signal'] else 'bearish'} momentum{x}.")
    if s["rsi14"] is not None:
        r = s["rsi14"]
        zone = "overbought (>70)" if r > 70 else "oversold (<30)" if r < 30 else "neutral (30-70)"
        lines.append(f"- RSI(14) {r:.1f}: {zone}.")
    if s["boll_up"] is not None:
        width = s["boll_up"] - s["boll_low"]
        pb = (c - s["boll_low"]) / width if width else 0.5
        lines.append(f"- Bollinger(20,2) {_f(s['boll_low'])} / {_f(s['boll_mid'])} / {_f(s['boll_up'])}: "
                     f"close at {pb * 100:.0f}% of the band"
                     f"{' (above upper band)' if pb > 1 else ' (below lower band)' if pb < 0 else ''}.")
    if s["atr14"] is not None:
        lines.append(f"- ATR(14) {_f(s['atr14'])} = {s['atr14'] / c * 100:.2f}% of price (daily volatility).")
    if s["vwma20"] is not None and s["sma20"] is not None:
        lines.append(f"- VWMA20 {_f(s['vwma20'])} vs SMA20 {_f(s['sma20'])}: "
                     f"{'volume is confirming the move' if (s['vwma20'] > s['sma20']) == (c > s['sma20']) else 'volume is not confirming the move'}.")
    return "\n".join(lines)


# ---------- team prompts ----------

BULL_PROMPT = """You are the Bull Researcher on a stock trading team.
Using ONLY the market report you are given, make the strongest evidence-based case for being long {symbol} right now.
Quote specific indicator readings. Do not invent news, earnings or numbers that are not in the report.
Reply with JSON only: {{"argument": "<at most 110 words>"}}"""

BEAR_PROMPT = """You are the Bear Researcher on a stock trading team.
Using ONLY the market report and the bull's argument, make the strongest evidence-based case AGAINST being long {symbol} right now,
and rebut the bull's weakest point. Quote specific indicator readings. Do not invent news, earnings or numbers.
Reply with JSON only: {{"argument": "<at most 110 words>"}}"""

MANAGER_PROMPT = """You are the Trader and Risk Manager of a stock trading team. You make the final call for {symbol}.
Weigh the market report and the bull/bear debate. Be disciplined: act only when the evidence clearly favours it.
Rules: long only (no shorting). Current position: {position}.
- BUY  = open a long position (only possible when flat).
- SELL = close the whole long position (only possible when holding).
- HOLD = do nothing today.
Reply with JSON only: {{"action": "BUY" | "SELL" | "HOLD", "confidence": <0 to 1>, "reason": "<at most 80 words, cite readings>"}}"""


def _json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        return json.loads(m.group(0)) if m else {}


def run_team(report: str, symbol: str, holding: bool, complete: Callable[[str, str], str],
             on_step: Callable[[str, str], None] | None = None) -> dict:
    """complete(system, user) -> raw model text. Returns the debate and a validated decision."""
    step = on_step or (lambda who, text: None)
    position = "HOLDING a long position" if holding else "FLAT (no position)"

    bull = str(_json(complete(BULL_PROMPT.format(symbol=symbol), report)).get("argument") or "").strip()
    step("bull", bull or "(no argument returned)")
    bear = str(_json(complete(BEAR_PROMPT.format(symbol=symbol),
                              f"{report}\n\nBull argument:\n{bull}")).get("argument") or "").strip()
    step("bear", bear or "(no argument returned)")
    raw = _json(complete(MANAGER_PROMPT.format(symbol=symbol, position=position),
                         f"{report}\n\nBull:\n{bull}\n\nBear:\n{bear}"))

    action = str(raw.get("action", "")).strip().upper()
    notes = []
    if action not in ACTIONS:
        notes.append(f"Model returned an invalid action {action!r}; treated as HOLD.")
        action = "HOLD"
    if action == "BUY" and holding:
        notes.append("BUY while already holding; treated as HOLD (one position at a time).")
        action = "HOLD"
    if action == "SELL" and not holding:
        notes.append("SELL while flat; treated as HOLD (long only, no shorting).")
        action = "HOLD"
    try:
        conf = max(0.0, min(1.0, float(raw.get("confidence", 0))))
    except (TypeError, ValueError):
        conf = 0.0
    reason = str(raw.get("reason") or "").strip()
    step("manager", f"{action} ({conf:.0%}) — {reason}")
    return {"action": action, "confidence": conf, "reason": reason, "bull": bull, "bear": bear, "notes": notes}
