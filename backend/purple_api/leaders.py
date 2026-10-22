"""Core strategy: momentum leaders from a wide list of NSE large and mid caps, only while NIFTY 50 is in an uptrend.

Research 22 Oct 2026 (daily prices, 97 stocks, 8 bps per side, decide on close and fill next open): settings were picked
on Nov 2022 - Oct 2024 and judged on Oct 2024 - Oct 2026, which was never used for picking. Holding the 5 strongest
stocks of the last 63 trading days, refreshed every 21 trading days, and holding cash while NIFTY 50 was below its
200-day average, made about +4% a year out of sample while NIFTY lost 3.3% a year (worst drop -9%); 17 of 18 nearby
settings were positive. Without the NIFTY filter the same momentum rules lost up to 22% a year. Caveat: the list is
today's large companies (survivorship bias). While NIFTY is below its 200-day average the desk's five agents trade.
"""
from __future__ import annotations

from .engine import Bar

WIDE = [s + ".NS" for s in """RELIANCE TCS HDFCBANK ICICIBANK INFY BHARTIARTL ITC LT SBIN AXISBANK KOTAKBANK HINDUNILVR
BAJFINANCE ASIANPAINT MARUTI SUNPHARMA TITAN ULTRACEMCO NESTLEIND WIPRO HCLTECH TECHM POWERGRID NTPC ONGC COALINDIA M&M
TATASTEEL JSWSTEEL HINDALCO ADANIENT ADANIPORTS BAJAJFINSV BAJAJ-AUTO HEROMOTOCO EICHERMOT DRREDDY CIPLA DIVISLAB
APOLLOHOSP GRASIM BRITANNIA INDUSINDBK SBILIFE HDFCLIFE TATACONSUM BPCL SHRIRAMFIN TRENT BEL HAL DLF PIDILITIND SIEMENS
ABB DMART GODREJCP DABUR MARICO COLPAL HAVELLS VOLTAS TVSMOTOR ASHOKLEY BANKBARODA PNB CANBK IDFCFIRSTB FEDERALBNK
AUBANK CHOLAFIN MUTHOOTFIN PERSISTENT COFORGE MPHASIS LUPIN AUROPHARMA ZYDUSLIFE TORNTPHARM POLYCAB DIXON IRCTC
TATAPOWER ADANIGREEN VEDL NMDC SAIL JINDALSTEL PFC RECLTD INDIGO ETERNAL BOSCHLTD CUMMINSIND BHARATFORG MRF
ICICIGI""".split()]
PICKS = 5
LOOKBACK = 63   # trading days, about 3 months
HOLD = 21       # trading days between refreshes, about a month
TREND = 200     # NIFTY 50 must close above its 200-day average
WEIGHT = 0.19   # per pick: 95% invested


def _before(rows: list[Bar], day: str) -> list[float]:
    return [b.close for b in rows if b.date[:10] < day]


def regime(market_daily: list[Bar], day: str) -> dict:
    """Uptrend test on closes before `day` (no look-ahead)."""
    c = _before(market_daily, day)
    if len(c) < TREND:
        return {"on": False, "gap_pct": None}
    avg = sum(c[-TREND:]) / TREND
    return {"on": c[-1] > avg, "gap_pct": round((c[-1] / avg - 1) * 100, 2)}


def strongest(daily: dict[str, list[Bar]], day: str, n: int = PICKS) -> list[str]:
    ret = {}
    for s, rows in daily.items():
        c = _before(rows, day)
        if len(c) > LOOKBACK and c[-LOOKBACK - 1] > 0:
            ret[s] = c[-1] / c[-LOOKBACK - 1] - 1
    return sorted(ret, key=ret.get, reverse=True)[:n]


def today(prev: dict | None, daily: dict[str, list[Bar]], market_daily: list[Bar], day: str) -> dict:
    """The core's state for `day`. Picks are kept for HOLD trading days while the uptrend lasts."""
    r = regime(market_daily, day)
    if not r["on"]:
        return {"on": False, "picks": [], "refreshed": None, "gap_pct": r["gap_pct"]}
    if prev and prev.get("on") and prev.get("picks") and prev.get("refreshed"):
        days = sum(1 for b in market_daily if prev["refreshed"] <= b.date[:10] < day)
        if days < HOLD:
            return {**prev, "gap_pct": r["gap_pct"]}
    return {"on": True, "picks": strongest(daily, day), "refreshed": day, "gap_pct": r["gap_pct"]}
