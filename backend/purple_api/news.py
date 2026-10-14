"""Headlines and trader posts for one stock, from free feeds that need no key.

- Google News RSS (Indian edition): company news; supports after:/before: date filters, so backtests can see the
  headlines of a past day without look-ahead.
- Reddit RSS search in r/IndianStreetBets and r/IndianStockMarket: retail-trader chatter (recent posts only).
- Yahoo Finance headline RSS: sparse for NSE symbols, kept as a third source.

StockTwits was tried and refused requests (HTTP 403, 15 Oct 2026); Reddit's JSON API also returned 403, its RSS works.
Items are data for the AI, never instructions; titles are trimmed and published times are checked against the
decision time so nothing from the future reaches a backtest.
"""
from __future__ import annotations

import email.utils
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx

from .market import IST

SOURCES = {
    "google": "Google News",
    "reddit": "Reddit (r/IndianStreetBets, r/IndianStockMarket)",
    "yahoo": "Yahoo Finance headlines",
}
LIVE_WINDOW = timedelta(days=3)  # Reddit/Yahoo serve recent items only; older decisions use Google's date filter
MAX_BYTES = 3_000_000
CACHE_S = 600
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PurpleTrade/1.0"}
_ATOM = "{http://www.w3.org/2005/Atom}"

_cache: dict[tuple, tuple[float, list]] = {}
_lock = threading.Lock()


class NewsError(RuntimeError):
    pass


def _get(url: str, params: dict) -> str:
    try:
        r = httpx.get(url, params=params, headers=_UA, timeout=15, follow_redirects=True)
    except httpx.HTTPError as e:
        raise NewsError(f"{type(e).__name__}") from e
    if r.status_code == 429:
        raise NewsError("rate-limited (429)")
    if r.status_code >= 400:
        raise NewsError(f"HTTP {r.status_code}")
    if len(r.content) > MAX_BYTES:
        raise NewsError("response too large")
    return r.text


def _clean(text: str | None, n: int = 200) -> str:
    t = re.sub(r"<[^>]+>", " ", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:n]


def _when(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        d = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _rss_items(xml: str, source: str) -> list[dict]:
    root = ET.fromstring(xml)
    out = []
    for it in root.iter("item"):
        out.append({"source": source, "title": _clean(it.findtext("title")), "link": it.findtext("link") or "",
                    "published": _when(it.findtext("pubDate")), "publisher": _clean(it.findtext("source"), 60)})
    for e in root.iter(f"{_ATOM}entry"):
        link = e.find(f"{_ATOM}link")
        out.append({"source": source, "title": _clean(e.findtext(f"{_ATOM}title")),
                    "link": link.get("href", "") if link is not None else "",
                    "published": _when(e.findtext(f"{_ATOM}published") or e.findtext(f"{_ATOM}updated")),
                    "publisher": _clean((e.find(f"{_ATOM}category").get("label") if e.find(f"{_ATOM}category") is not None else ""), 60)})
    return [i for i in out if i["title"]]


def _query(name: str, ticker: str) -> str:
    base = ticker.split(".")[0]
    nm = re.sub(r"\b(limited|ltd\.?)\b", "", name or "", flags=re.I).strip() or base
    return f'"{nm}"' if nm.upper() == base else f'"{nm}" OR {base}'


def _fetch(source: str, name: str, ticker: str, upto: datetime | None) -> list[dict]:
    q = _query(name, ticker)
    if source == "google":
        params = {"q": f"{q} stock", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
        if upto is not None:  # Google's operators work on dates; the published check below trims the day itself
            day = upto.astimezone(IST).date()
            params["q"] += f" after:{day - timedelta(days=3)} before:{day + timedelta(days=1)}"
        return _rss_items(_get("https://news.google.com/rss/search", params), source)
    if source == "reddit":
        return _rss_items(_get("https://www.reddit.com/r/IndianStreetBets+IndianStockMarket/search.rss",
                               {"q": q, "restrict_sr": "on", "sort": "new", "t": "week"}), source)
    if source == "yahoo":
        return _rss_items(_get("https://feeds.finance.yahoo.com/rss/2.0/headline",
                               {"s": ticker, "region": "IN", "lang": "en-IN"}), source)
    raise NewsError(f"unknown source {source!r}")


def headlines(name: str, ticker: str, sources: list[str], upto: datetime | None = None,
              limit: int = 25, now: datetime | None = None) -> dict:
    """Newest items published at or before `upto` (default: now), at most `limit`, plus per-source notes.
    Returns {"items": [...], "notes": [...]}; a failing source is noted, not fatal."""
    now = now or datetime.now(timezone.utc)
    cutoff = upto or now
    live = now - cutoff <= LIVE_WINDOW
    items, notes = [], []
    for src in sources:
        if src not in SOURCES:
            continue
        if src != "google" and not live:
            notes.append(f"{SOURCES[src]}: only recent posts are available, skipped for {cutoff.astimezone(IST):%d %b %Y}.")
            continue
        key = (src, ticker, None if live else cutoff.astimezone(IST).date())
        with _lock:
            hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_S:
            got = hit[1]
        else:
            try:
                got = _fetch(src, name, ticker, None if live else cutoff)
            except (NewsError, ET.ParseError) as e:
                notes.append(f"{SOURCES[src]} unavailable ({e}).")
                continue
            with _lock:
                _cache[key] = (time.time(), got)
        items += [i for i in got if i["published"] and i["published"] <= cutoff]
    seen, uniq = set(), []
    for i in sorted(items, key=lambda x: x["published"], reverse=True):
        k = re.sub(r"\W+", "", i["title"].lower())[:60]
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    return {"items": uniq[:limit], "notes": notes}


def digest(items: list[dict], at: datetime) -> str:
    """Numbered plain-text list for the AI: age, source, publisher, title."""
    if not items:
        return "(no headlines or posts found)"
    lines = []
    for n, i in enumerate(items, 1):
        hrs = max(0, (at - i["published"]).total_seconds() / 3600)
        age = f"{hrs:.0f} h ago" if hrs < 48 else f"{hrs / 24:.0f} d ago"
        pub = f" ({i['publisher']})" if i.get("publisher") else ""
        lines.append(f"[{n}] {age} · {i['source']}{pub}: {i['title']}")
    return "\n".join(lines)
