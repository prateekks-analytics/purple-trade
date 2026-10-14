"""Market prices from Yahoo Finance's public chart endpoint: no key, no extra package.

Unofficial and delayed (NSE quotes ~15 min); not verified against NSE. Daily bars count only completed sessions:
a bar dated today is dropped until 16:00 IST, so rules still decide on a finished close and fill at the next open.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import httpx

from .engine import Bar

SOURCE = "Yahoo Finance (unofficial, delayed; not verified against NSE)"
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
IST = timezone(timedelta(hours=5, minutes=30))
SETTLED = (16, 0)  # IST time after which today's daily bar is treated as final


class MarketError(RuntimeError):
    pass


def ticker(symbol: str) -> str:
    """'reliance' -> 'RELIANCE.NS'; tickers that already name an exchange or index are kept."""
    s = re.sub(r"[^A-Za-z0-9.&^_-]", "", symbol or "").upper()
    if not s:
        raise MarketError("Enter an NSE symbol, e.g. RELIANCE.")
    return s if "." in s or s.startswith("^") else f"{s}.NS"


def _fetch(url: str, params: dict) -> dict:
    try:
        r = httpx.get(url, params=params, headers={"User-Agent": "Mozilla/5.0 (PurpleTrade)"}, timeout=15)
    except httpx.HTTPError as e:
        raise MarketError(f"Yahoo Finance can't be reached ({type(e).__name__}).") from e
    if r.status_code == 404:
        raise MarketError("Yahoo Finance doesn't know that symbol.")
    if r.status_code == 429:
        raise MarketError("Yahoo Finance is rate-limiting requests; try again in a minute.")
    if r.status_code >= 400:
        raise MarketError(f"Yahoo Finance answered {r.status_code}.")
    return r.json()


def _chart(tk: str, range_: str, interval: str) -> dict:
    j = _fetch(CHART.format(tk), {"range": range_, "interval": interval, "includePrePost": "false"})
    res = (j.get("chart") or {}).get("result") or []
    if not res:
        err = ((j.get("chart") or {}).get("error") or {}).get("description")
        raise MarketError(err or "Yahoo Finance returned no data for that symbol.")
    return res[0]


def daily_bars(symbol: str, range_: str = "2y", now: datetime | None = None) -> list[Bar]:
    """Completed daily sessions, oldest first, prices rounded to the paisa."""
    tk = ticker(symbol)
    c = _chart(tk, range_, "1d")
    q = ((c.get("indicators") or {}).get("quote") or [{}])[0]
    now = (now or datetime.now(timezone.utc)).astimezone(IST)
    today, settled = now.date().isoformat(), (now.hour, now.minute) >= SETTLED
    meta = c.get("meta") or {}
    last_trade = meta.get("regularMarketTime")
    last_day = datetime.fromtimestamp(last_trade, IST).date().isoformat() if last_trade else None
    stamps = c.get("timestamp") or []
    bars, seen = [], set()
    for i, ts in enumerate(stamps):
        o, h, l, cl = (q.get(k, [None])[i] for k in ("open", "high", "low", "close"))
        d = datetime.fromtimestamp(ts, IST).date().isoformat()
        if cl is None and i == len(stamps) - 1 and d == last_day:
            cl = meta.get("regularMarketPrice")  # Yahoo often leaves the newest daily close blank; meta has it
        if None in (o, h, l, cl):
            continue
        if d in seen or (d == today and not settled):
            continue
        seen.add(d)
        bars.append(Bar(d, round(o, 2), round(h, 2), round(l, 2), round(cl, 2), float(q.get("volume", [0])[i] or 0)))
    if len(bars) < 2:
        raise MarketError(f"Yahoo Finance returned too few daily prices for {tk}.")
    return bars


def quote(symbol: str, now: datetime | None = None) -> dict:
    """Latest traded price (delayed) and whether the regular session is open now."""
    tk = ticker(symbol)
    m = _chart(tk, "1d", "5m").get("meta") or {}
    price = m.get("regularMarketPrice")
    if price is None:
        raise MarketError(f"Yahoo Finance has no current price for {tk}.")
    prev = m.get("previousClose") or m.get("chartPreviousClose")
    reg = (m.get("currentTradingPeriod") or {}).get("regular") or {}
    t = (now or datetime.now(timezone.utc)).timestamp()
    at = m.get("regularMarketTime")
    return {
        "ticker": tk, "currency": m.get("currency"), "price": round(price, 2),
        "prev_close": round(prev, 2) if prev else None,
        "change_pct": round((price / prev - 1) * 100, 2) if prev else None,
        "time": datetime.fromtimestamp(at, IST).isoformat() if at else None,
        "session_open": bool(reg) and reg.get("start", 0) <= t < reg.get("end", 0),
        "source": SOURCE,
    }
