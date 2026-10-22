"""Market prices from Yahoo Finance's public chart endpoint: no key, no extra package.

Unofficial and delayed (NSE quotes ~15 min); not verified against NSE. Daily bars count only completed sessions:
a bar dated today is dropped until 16:00 IST, so rules still decide on a finished close and fill at the next open.
Intraday bars (5m/15m/30m) likewise count only once their period has ended.

Yahoo limits request rates without publishing the limit. A 429 answer pauses all Yahoo calls for a minute and is
reported by status(), which the UI shows as a warning. A broker feed (real time, needs the user's own API key)
can be added later as another entry in FEEDS.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import httpx

from .engine import Bar

SOURCE = "Yahoo Finance (unofficial, delayed; not verified against NSE)"
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
IST = timezone(timedelta(hours=5, minutes=30))
SETTLED = (16, 0)  # IST time after which today's daily bar is treated as final
INTERVALS = {"5m": 300, "15m": 900, "30m": 1800}
INTRADAY_RANGE = "1mo"  # enough warm-up for SMA 200 on 5-minute bars; Yahoo keeps 60 days of these
PAUSE_S = 60

FEEDS = [
    {"id": "yahoo", "label": "Yahoo Finance", "connected": True, "delay": "about 15 minutes", "cost": "free",
     "note": "Unofficial; rate limits are not published."},
    {"id": "broker", "label": "Broker data API (Upstox, Angel One SmartAPI, Zerodha Kite)", "connected": False,
     "delay": "real time", "cost": "varies (UNVERIFIED)",
     "note": "Needs your own broker account and API key. Not connected yet."},
]


class MarketError(RuntimeError):
    pass


class RateLimited(MarketError):
    pass


_lock = threading.Lock()
_state = {"paused_until": 0.0, "last_error": None, "last_error_at": None}
_calls: deque = deque()


def status() -> dict:
    """Feed health for the UI: calls in the last hour and whether Yahoo is currently refusing requests."""
    now = time.time()
    with _lock:
        while _calls and _calls[0] < now - 3600:
            _calls.popleft()
        wait = max(0, int(_state["paused_until"] - now))
        return {"feed": "yahoo", "feeds": FEEDS, "calls_last_hour": len(_calls), "rate_limited": wait > 0,
                "retry_in_s": wait, "last_error": _state["last_error"], "last_error_at": _state["last_error_at"]}


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
        raise RateLimited("Yahoo Finance is limiting requests (too many in a short time). Purple pauses for a minute.")
    if r.status_code >= 400:
        raise MarketError(f"Yahoo Finance answered {r.status_code}.")
    return r.json()


def _guarded(url: str, params: dict) -> dict:
    now = time.time()
    with _lock:
        if now < _state["paused_until"]:
            raise RateLimited(f"Yahoo Finance is limiting requests; Purple retries in {int(_state['paused_until'] - now)} s.")
        _calls.append(now)
    try:
        return _fetch(url, params)
    except MarketError as e:
        with _lock:
            _state["last_error"], _state["last_error_at"] = str(e), datetime.now(IST).isoformat(timespec="seconds")
            if isinstance(e, RateLimited):
                _state["paused_until"] = time.time() + PAUSE_S
        raise


def _chart(tk: str, range_: str, interval: str) -> dict:
    j = _guarded(CHART.format(tk), {"range": range_, "interval": interval, "includePrePost": "false"})
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


def intraday_bars(symbol: str, interval: str = "5m", range_: str = INTRADAY_RANGE,
                  now: datetime | None = None) -> list[Bar]:
    """Completed intraday bars, oldest first, dated 'YYYY-MM-DD HH:MM' in IST (bar start time)."""
    if interval not in INTERVALS:
        raise MarketError(f"Unsupported bar size {interval!r}; choose {', '.join(INTERVALS)}.")
    tk = ticker(symbol)
    c = _chart(tk, range_, interval)
    q = ((c.get("indicators") or {}).get("quote") or [{}])[0]
    t_now = (now or datetime.now(timezone.utc)).timestamp()
    step = INTERVALS[interval]
    bars, seen = [], set()
    for i, ts in enumerate(c.get("timestamp") or []):
        o, h, l, cl = (q.get(k, [None])[i] for k in ("open", "high", "low", "close"))
        if None in (o, h, l, cl) or ts + step > t_now:  # gap, or the bar is still forming
            continue
        d = datetime.fromtimestamp(ts, IST).strftime("%Y-%m-%d %H:%M")
        if d in seen:
            continue
        seen.add(d)
        bars.append(Bar(d, round(o, 2), round(h, 2), round(l, 2), round(cl, 2), float(q.get("volume", [0])[i] or 0)))
    return bars


def fundamentals(symbol: str) -> list[dict]:
    """Annual figures (revenue, profit, EPS, debt, equity, free cash flow) with the date each period ended."""
    tk = ticker(symbol)
    types = ["annualTotalRevenue", "annualNetIncome", "annualDilutedEPS", "annualTotalDebt",
             "annualStockholdersEquity", "annualFreeCashFlow"]
    j = _guarded(f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{tk}",
                 {"type": ",".join(types), "period1": 1262304000, "period2": int(time.time()) + 86400})
    out = []
    for res in (j.get("timeseries") or {}).get("result") or []:
        kind = ((res.get("meta") or {}).get("type") or [None])[0]
        for row in res.get(kind) or []:
            if row and row.get("asOfDate") and (row.get("reportedValue") or {}).get("raw") is not None:
                out.append({"type": kind.removeprefix("annual"), "as_of": row["asOfDate"],
                            "value": row["reportedValue"]["raw"], "currency": row.get("currencyCode")})
    return sorted(out, key=lambda r: (r["as_of"], r["type"]))


def recent_prices(symbol: str, minutes: int = 30, now: datetime | None = None) -> tuple[float, list[float]]:
    """One call: the latest price and every 5-minute close of the last `minutes` (today only), for the crash guard."""
    c = _chart(ticker(symbol), "1d", "5m")
    price = (c.get("meta") or {}).get("regularMarketPrice")
    if price is None:
        raise MarketError(f"Yahoo Finance has no current price for {symbol}.")
    q = ((c.get("indicators") or {}).get("quote") or [{}])[0]
    since = (now or datetime.now(timezone.utc)).timestamp() - minutes * 60 - 300
    closes = [cl for ts, cl in zip(c.get("timestamp") or [], q.get("close") or []) if cl is not None and ts >= since]
    return float(price), [float(x) for x in closes]


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
        "ticker": tk, "name": m.get("longName") or m.get("shortName"), "currency": m.get("currency"), "price": round(price, 2),
        "prev_close": round(prev, 2) if prev else None,
        "change_pct": round((price / prev - 1) * 100, 2) if prev else None,
        "time": datetime.fromtimestamp(at, IST).isoformat() if at else None,
        "session_open": bool(reg) and reg.get("start", 0) <= t < reg.get("end", 0),
        "source": SOURCE,
    }
