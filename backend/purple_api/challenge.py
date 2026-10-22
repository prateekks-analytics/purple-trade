"""Beat the market: replay a rule bot week by week against NIFTY 50, let an AI coach improve it, then race it live.

A "week" is WEEK trading sessions. Each week starts flat with the same capital at a session's close (the bot may buy
at the next open) and ends at the close WEEK sessions later. The market is NIFTY 50 over the same two closes, so
staying in cash during a falling week counts as beating the market.
"""
from __future__ import annotations

from .describe import condition_text, warmup_bars
from .engine import Bar, run_backtest
from .schema import Strategy

WEEK = 7  # trading sessions per challenge week
WEEKS = 24  # weeks replayed (about eight months)
HOLDOUT = 8  # newest weeks the AI coach never sees, used to check its change on unseen weeks
MARKET = "^NSEI"
MARKET_NAME = "NIFTY 50"
COACH_ROUNDS = 3


def close_on(closes: dict[str, float], dates: list[str], day: str) -> float | None:
    """NIFTY close on `day`, else the latest close before it (index and stock calendars can differ by a day)."""
    if day in closes:
        return closes[day]
    prev = [d for d in dates if d <= day]
    return closes[prev[-1]] if prev else None


def weekly(strategy: Strategy, bars: list[Bar], market: list[Bar], weeks: int = WEEKS, capital: float = 100_000) -> dict:
    """Bot vs market for the last `weeks` non-overlapping weeks. Raises ValueError when history is too short."""
    warm = warmup_bars(strategy)
    n = min(weeks, (len(bars) - 1 - warm) // WEEK)
    if n < 1:
        raise ValueError(f"Not enough price history: these rules need {warm} days of warm-up plus {WEEK} more.")
    st = strategy.model_copy(update={"initial_capital": capital})
    closes = {b.date: b.close for b in market}
    mdates = sorted(closes)
    out = []
    for k in range(n, 0, -1):
        end = len(bars) - 1 - (k - 1) * WEEK
        start = end - WEEK
        lo = max(0, start - warm - 5)
        res = run_backtest(st, bars[lo:end + 1], trade_from=start - lo)
        m0, m1 = close_on(closes, mdates, bars[start].date), close_on(closes, mdates, bars[end].date)
        if not m0 or not m1:
            continue
        bot = res["metrics"]["end_equity"] / capital - 1
        mkt = m1 / m0 - 1
        out.append({
            "start": bars[start].date, "end": bars[end].date,
            "bot_pct": round(bot * 100, 2), "market_pct": round(mkt * 100, 2),
            "edge_rupees": round((bot - mkt) * capital), "beat": bot > mkt,
            "trades": len(res["trades"]), "in_market": res["metrics"]["exposure_pct"] > 0,
        })
    return {"weeks": out, "summary": summarize(out, capital)}


def summarize(weeks: list[dict], capital: float = 100_000) -> dict:
    if not weeks:
        return {"weeks": 0, "beat": 0, "avg_edge": 0, "total_edge": 0, "verdict": "No weeks to judge."}
    beat = sum(w["beat"] for w in weeks)
    total = sum(w["edge_rupees"] for w in weeks)
    avg = round(total / len(weeks))
    idle = sum(not w["in_market"] for w in weeks)
    cash = sum(w["market_pct"] < 0 for w in weeks)  # weeks that simply holding cash would also have won
    if idle * 2 > len(weeks):
        verdict = ("Mostly sat in cash: it only 'wins' the weeks the market falls. "
                   "Ask the AI coach to make it trade more.")
    elif beat <= cash:
        verdict = "No better than holding cash. Ask the AI coach to improve it."
    elif beat * 3 >= len(weeks) * 2 and avg > 0:
        verdict = "Strong: it beat the market in most weeks. Race it live for a week."
    elif beat * 2 > len(weeks) and avg > 0:
        verdict = "Promising: it beat the market more often than not. Try the AI coach or race it live."
    else:
        verdict = "Not ready: the market won more weeks. Ask the AI coach to improve it."
    return {"weeks": len(weeks), "beat": beat, "avg_edge": avg, "total_edge": total, "idle_weeks": idle,
            "cash_beat": cash, "capital": capital, "verdict": verdict}


def split(card: dict) -> tuple[dict, dict]:
    """Older weeks (the coach learns from these) and the newest HOLDOUT weeks (kept from the coach)."""
    w = card["weeks"]
    cut = max(1, len(w) - HOLDOUT) if len(w) > HOLDOUT else len(w)
    return summarize(w[:cut]), summarize(w[cut:])


def score(s: dict) -> tuple:
    """Higher is better: weeks won first, then average weekly edge."""
    return (s["beat"], s["avg_edge"])


def coach_message(strategy: Strategy, learn: dict, learn_weeks: list[dict], tried: list[dict], hint: str = "") -> str:
    lost = sorted((w for w in learn_weeks if not w["beat"]), key=lambda w: w["edge_rupees"])[:4]
    lines = [
        f"Goal: beat {MARKET_NAME} in as many {WEEK}-session weeks as possible. Each week starts in cash with Rs 1,00,000.",
        f"Current rules: BUY when {condition_text(strategy.entry)}; SELL when {condition_text(strategy.exit)}.",
        f"Result: beat the market in {learn['beat']} of {learn['weeks']} weeks; average week {learn['avg_edge']:+,} rupees "
        f"versus the market; {learn.get('idle_weeks', 0)} weeks it never bought; holding cash alone would have won "
        f"{learn.get('cash_beat', 0)} weeks, so it must beat that too.",
    ]
    if lost:
        lines.append("Worst weeks: " + "; ".join(
            f"{w['start']}..{w['end']} bot {w['bot_pct']:+.2f}% vs market {w['market_pct']:+.2f}%" for w in lost))
    for t in tried:
        lines.append(f"Already tried (do not repeat): {t['change']} -> beat {t['beat']} of {t['weeks']} weeks.")
    lines.append("Propose ONE clear change to the buy and/or sell rules that should win more weeks against the market. "
                 "Keep it simple (at most three conditions per side), long only, daily bars. Weeks are short, so rules "
                 "that wait for 200-day signals rarely trade. Put a one-sentence plain explanation of the change in notes.")
    if hint.strip():
        lines.append(f"The person also asked: {hint.strip()[:400]}")
    return "\n".join(lines)

