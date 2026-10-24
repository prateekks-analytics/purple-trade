"""Strategy lab: how the company adds and retires strategies, like a fund (owner's plan, 25 Oct 2026).

Every candidate climbs the same ladder: bench (years of backtest with real costs) -> shadow (paper only, tracked in
the daily review, no money) -> trial (about 10% of the money) -> live -> retired. Long backtests are the main
evidence: live results need hundreds of trading days to prove an edge, so shadow days only check that a strategy
trades the way its backtest said. Risk breaches demote at once; weak returns only at the 1-, 3- and 6-month reviews.
Nothing here trades: promotions are made in code after the owner approves them in the weekly board report.

Risk levels set what a client allows (a questionnaire can fill this in later). "medium" is today's bot.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from .engine import Bar

STAGES = ["bench", "shadow", "trial", "live", "retired"]
REVIEW_MONTHS = (1, 3, 6)
CHECK_DAYS = 20  # trading days before a shadow's trade count is compared with its backtest
LIVE_WEIGHT_DAYS = 250  # live evidence counts days / (days + 250) against the backtest

RISK_LEVELS = {
    "low": {"name": "Low", "shorts": False, "futures": False, "max_drawdown_pct": 5.0,
            "about": "Long only in shares; the bot cuts risk after a 5% fall from its high."},
    "medium": {"name": "Medium", "shorts": False, "futures": False, "max_drawdown_pct": 10.0,
               "about": "Today's bot: long only in shares, no futures."},
    "high": {"name": "High", "shorts": True, "futures": True, "max_drawdown_pct": 20.0,
             "about": "Shares plus NIFTY futures, long and short; accepts a 20% fall from the high."},
}

# NIFTY futures, per side as a fraction of the traded value: STT 0.02% on sells, stamp duty 0.002% on buys, NSE
# 0.00173% + SEBI 0.0001%, GST 18% on those two, slippage 0.01% (very liquid). Rates from broker pages, UNVERIFIED.
FUT_BUY = 0.00002 + (0.0000173 + 0.000001) * 1.18 + 0.0001
FUT_SELL = 0.0002 + (0.0000173 + 0.000001) * 1.18 + 0.0001

CANDIDATES = [
    {"id": "trend_hourly", "name": "Hourly trend (NIFTY futures)", "team": "Index", "stage": "shadow",
     "since": "2026-10-26", "needs": ["futures", "shorts"],
     "rule": "Supertrend 10x3 on hourly NIFTY bars: long when it points up, short when it points down.",
     "bench": {"period": "Nov 2023 - Oct 2026, hourly", "return_pct": 26.7, "nifty_pct": 16.3, "max_drawdown_pct": -17.8,
               "trades_per_month": 4.7, "edge_per_year_pct": 3.5,
               "note": "Positive in all 12 nearby settings, but the same rule on daily bars lost over 2007-2026. "
                       "Only 3 years of hourly data exist, so the evidence is weak."}},
    {"id": "bear_short", "name": "Bear-market short (NIFTY futures)", "team": "Index", "stage": "shadow",
     "since": "2026-10-26", "needs": ["futures", "shorts"],
     "rule": "Only while NIFTY closed below its 200-day average the day before: short when the hourly Supertrend "
             "10x3 points down, otherwise flat.",
     "bench": {"period": "Nov 2023 - Oct 2026, hourly", "return_pct": 11.9, "nifty_pct": 16.3, "max_drawdown_pct": -8.8,
               "trades_per_month": 1.6, "edge_per_year_pct": None,
               "note": "Made money in all 5 settings tried and stayed flat in the bull run (a hedge, not a "
                       "replacement). The daily version lost 40-53% over 2007-2026, so the evidence is weak."}},
]


def risk_level() -> dict:
    key = os.environ.get("PURPLE_RISK_LEVEL", "medium").lower()
    return {"id": key if key in RISK_LEVELS else "medium", **RISK_LEVELS.get(key, RISK_LEVELS["medium"])}


# ---------- signals ----------

def hourly(bars: list[Bar]) -> list[Bar]:
    """Hourly bars from 30-minute bars (09:15+09:45, 10:15+10:45, ..., 15:15 alone), like Yahoo's 60m bars.
    An hour with only its first half done (other than 15:15) is left out: it has not closed yet."""
    out, i = [], 0
    while i < len(bars):
        b = bars[i]
        hm = b.date[11:16]
        mate = bars[i + 1] if i + 1 < len(bars) and bars[i + 1].date[:10] == b.date[:10] else None
        first_half = hm >= "09:15" and (int(hm[:2]) * 60 + int(hm[3:]) - 555) % 60 == 0
        if first_half and hm != "15:15" and mate is not None:
            out.append(Bar(b.date, b.open, max(b.high, mate.high), min(b.low, mate.low), mate.close, b.volume + mate.volume))
            i += 2
        elif first_half and hm != "15:15" and i == len(bars) - 1:
            break  # the newest hour is still open
        else:
            out.append(b)
            i += 1
    return out


def supertrend(bars: list[Bar], n: int = 10, mult: float = 3.0) -> list[int]:
    """+1 / -1 per bar (0 during the warm-up of 3n bars). ATR uses Wilder smoothing."""
    out, atr = [0] * len(bars), None
    fu = fl = 0.0
    t = 1
    for i, b in enumerate(bars):
        pc = bars[i - 1].close if i else None
        tr = b.high - b.low if pc is None else max(b.high - b.low, abs(b.high - pc), abs(b.low - pc))
        atr = tr if atr is None else atr + (tr - atr) / n
        mid = (b.high + b.low) / 2
        ub, lb = mid + mult * atr, mid - mult * atr
        if i == 0:
            fu, fl = ub, lb
            continue
        pfu, pfl = fu, fl
        fu = ub if (ub < pfu or pc > pfu) else pfu
        fl = lb if (lb > pfl or pc < pfl) else pfl
        if b.close > pfu:
            t = 1
        elif b.close < pfl:
            t = -1
        out[i] = t if i >= 3 * n else 0
    return out


def below_200(daily: list[Bar]) -> dict[str, bool]:
    """Per day D: did NIFTY close below its 200-day average on the trading day before D? (Known before D opens.)"""
    out, closes = {}, []
    for i, b in enumerate(daily):
        if len(closes) >= 200:
            out[b.date[:10]] = closes[-1] < sum(closes[-200:]) / 200
        closes.append(b.close)
    return out


def positions(cid: str, hours: list[Bar], daily: list[Bar]) -> list[int]:
    st = supertrend(hours)
    if cid == "trend_hourly":
        return st
    if cid == "bear_short":
        bear = below_200(daily)
        return [-1 if s < 0 and bear.get(h.date[:10], False) else 0 for s, h in zip(st, hours)]
    raise KeyError(cid)


# ---------- paper results ----------

def simulate(hours: list[Bar], pos: list[int], start: str, capital: float) -> dict:
    """Paper account from the first hour at or after `start`: the position decided on an hour's close is taken at the
    next hour's open (no hindsight). Futures charges and slippage on every change; whole notional, no leverage."""
    value, held, peak, dd = capital, 0, capital, 0.0
    equity, trades = [], []
    i0 = next((i for i, h in enumerate(hours) if h.date >= start), len(hours))
    for i in range(i0, len(hours)):
        h = hours[i]
        want = pos[i - 1] if i > 0 else 0
        if want != held:
            for side, size in (("SELL", max(held, 0) + max(-want, 0)), ("BUY", max(-held, 0) + max(want, 0))):
                if size:
                    value -= value * size * (FUT_SELL if side == "SELL" else FUT_BUY)
            trades.append({"time": h.date, "from": held, "to": want, "price": round(h.open, 2)})
            held = want
        nxt = hours[i + 1].open if i + 1 < len(hours) else h.close
        value *= 1 + held * (nxt / h.open - 1)
        peak = max(peak, value)
        dd = min(dd, value / peak - 1)
        equity.append({"time": h.date, "value": round(value, 2)})
    return {"equity": equity, "trades": trades, "position": held,
            "return_pct": round((value / capital - 1) * 100, 2), "max_drawdown_pct": round(dd * 100, 2)}


def _months_after(day: str, m: int) -> str:
    d = date.fromisoformat(day)
    y, mo = divmod(d.month - 1 + m, 12)
    return date(d.year + y, mo + 1, min(d.day, 28)).isoformat()


def assess(c: dict, sim: dict, nifty_pct: float | None, days: int, today: str, level: dict) -> dict:
    """Where a candidate stands and what the board should do. Risk first, returns only at the scheduled reviews."""
    b = c["bench"]
    reviews = [_months_after(c["since"], m) for m in REVIEW_MONTHS]
    nxt = next((r for r in reviews if r > today), None)
    due = [r for r in reviews if r <= today]
    w = days / (days + LIVE_WEIGHT_DAYS)
    live_edge = None
    if days >= CHECK_DAYS and nifty_pct is not None:
        live_edge = round((sim["return_pct"] - nifty_pct) * 250 / days, 1)  # per year, rough
    blended = None if b.get("edge_per_year_pct") is None or live_edge is None else \
        round((1 - w) * b["edge_per_year_pct"] + w * live_edge, 1)
    flags = []
    if sim["max_drawdown_pct"] < 1.5 * b["max_drawdown_pct"]:
        flags.append(f"Fell {sim['max_drawdown_pct']:.1f}% from its high, beyond 1.5x its backtest's worst "
                     f"({b['max_drawdown_pct']:.1f}%).")
    if days >= CHECK_DAYS:
        per_month = len(sim["trades"]) * 21 / days
        if not (b["trades_per_month"] / 3 <= per_month <= b["trades_per_month"] * 3 + 1):
            flags.append(f"Trades {per_month:.1f} times a month vs {b['trades_per_month']} in its backtest.")
    blocked = [n for n in c["needs"] if not level.get(n)]
    if flags:
        verdict = "Demote now: " + " ".join(flags)
    elif due and days >= CHECK_DAYS and nifty_pct is not None and sim["return_pct"] > nifty_pct:
        verdict = (f"Review due ({due[-1]}): ahead of NIFTY and within its risk. "
                   + (f"Promotion needs a risk level that allows {', '.join(blocked)}." if blocked
                      else "The owner may approve a trial at 10% of the money."))
    elif due and days >= CHECK_DAYS:
        verdict = f"Review due ({due[-1]}): behind NIFTY in shadow. Keep watching; retire if still behind at 6 months."
    else:
        verdict = f"Keep in {c['stage']}. Too early to judge" + (f"; first review {nxt}." if nxt else ".")
    return {"days": days, "next_review": nxt, "live_weight": round(w, 2), "live_edge_per_year_pct": live_edge,
            "blended_edge_per_year_pct": blended, "flags": flags, "blocked_by_risk_level": blocked, "verdict": verdict}


def report(market30: list[Bar], daily: list[Bar], today: str | None = None, capital: float = 500_000) -> dict:
    """The lab's state for the review pack and the weekly board report."""
    today = today or datetime.now().date().isoformat()
    hours = hourly(market30)
    level = risk_level()
    rows = []
    for c in CANDIDATES:
        row = {k: c[k] for k in ("id", "name", "team", "stage", "since", "needs", "rule", "bench")}
        if c["stage"] in ("shadow", "trial") and hours:
            sim = simulate(hours, positions(c["id"], hours, daily), c["since"], capital)
            days = len({e["time"][:10] for e in sim["equity"]})
            first = next((h for h in hours if h.date >= c["since"]), None)
            nifty = round((hours[-1].close / first.open - 1) * 100, 2) if first else None
            row.update(paper={k: sim[k] for k in ("return_pct", "max_drawdown_pct", "position")},
                       trades=len(sim["trades"]), last_trades=sim["trades"][-5:], nifty_pct=nifty,
                       today_pct=_day_pct(sim["equity"], today),
                       assessment=assess(c, sim, nifty, days, today, level))
        rows.append(row)
    return {"risk_level": level, "candidates": rows, "data_time": hours[-1].date if hours else None,
            "note": "Paper only: nothing here trades. Promotions need the owner's approval in the weekly board report."}


def _day_pct(equity: list[dict], day: str) -> float | None:
    before = [e["value"] for e in equity if e["time"][:10] < day]
    on = [e["value"] for e in equity if e["time"][:10] == day]
    if not on:
        return None
    base = before[-1] if before else None
    return round((on[-1] / base - 1) * 100, 2) if base else None


def markdown(lab: dict) -> list[str]:
    lv = lab["risk_level"]
    L = ["## Strategy lab (paper only, not traded)", "",
         f"Risk level: {lv['name']} ({lv['about'].rstrip('.')}). Long backtests are the main evidence; shadow days check behaviour.", "",
         "| candidate | stage | since | paper since entry | NIFTY same time | worst fall | trades | today | verdict |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in lab["candidates"]:
        if "paper" not in r:
            L.append(f"| {r['name']} | {r['stage']} | {r['since']} | | | | | | |")
            continue
        p, a = r["paper"], r["assessment"]
        f = (lambda x: "—" if x is None else f"{x:+.2f}%")
        L.append(f"| {r['name']} | {r['stage']} | {r['since']} | {f(p['return_pct'])} | {f(r['nifty_pct'])} | "
                 f"{p['max_drawdown_pct']:.2f}% | {r['trades']} | {f(r['today_pct'])} | {a['verdict']} |")
    L.append("")
    for r in lab["candidates"]:
        L.append(f"- {r['name']}: {r['rule']} Backtest {r['bench']['period']}: {r['bench']['return_pct']:+.1f}% vs NIFTY "
                 f"{r['bench']['nifty_pct']:+.1f}%, worst fall {r['bench']['max_drawdown_pct']:.1f}%. {r['bench']['note']}")
    return L + [""]
