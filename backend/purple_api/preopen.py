"""Pre-open read (owner, 25 Oct 2026): tracked, never traded.

Between 09:00 and 09:15 IST the bot reads the overnight cues (US close, Japan and Hong Kong so far today, India VIX
and NIFTY yesterday) and counts warning signs, using the thresholds of the 23 Oct research. The review then asks:
what would selling half the company's shares at the 09:15 open and buying them back at the close have made? It is
worked out every day, so the coach can compare flagged days with the rest. The 23 Oct test over 3 years said this
loses (NIFTY usually recovers after a bad open), so it only enters the strategy lab if months of live records
disagree. GIFT Nifty is not on Yahoo, so it is not read.
"""
from __future__ import annotations

from datetime import datetime

from . import costs, market

CUES = [  # symbol, plain name, threshold (% change that counts as a warning sign)
    ("^GSPC", "US S&P 500 (last close)", -1.0),
    ("^N225", "Japan Nikkei 225 (so far today)", -1.5),
    ("^HSI", "Hong Kong Hang Seng (so far today)", -1.5),
    ("^INDIAVIX", "India VIX, fear gauge (yesterday)", 5.0),
    ("^NSEI", "NIFTY 50 (yesterday)", -1.0),
]
FLAG_SIGNS = 2
WINDOW = ((9, 0), (9, 15))  # IST: after Asia opens, before NSE does
SELL_SHARE = 0.5


def read(now: datetime | None = None, get=market.quote) -> dict:
    """The cues as Yahoo shows them now. A cue Yahoo cannot give is kept with change None (no sign)."""
    now = (now or datetime.now(market.IST)).astimezone(market.IST)
    rows, signs = [], 0
    for sym, name, th in CUES:
        try:
            q = get(sym)
            ch, at = q.get("change_pct"), q.get("time")
        except market.MarketError:
            ch, at = None, None
        sign = ch is not None and (ch >= th if th > 0 else ch <= th)
        signs += sign
        rows.append({"symbol": sym, "name": name, "change_pct": ch, "threshold_pct": th, "sign": bool(sign), "time": at})
    return {"at": now.isoformat(timespec="minutes"), "cues": rows, "signs": signs, "flagged": signs >= FLAG_SIGNS}


def in_window(ist: datetime) -> bool:
    return ist.weekday() < 5 and WINDOW[0] <= (ist.hour, ist.minute) < WINDOW[1]


def held_before(trades: list[dict], day: str) -> dict[str, int]:
    """Shares the company held going into `day` (from its trade list)."""
    q: dict[str, int] = {}
    for t in trades:
        if t["time"] == "now" or t["time"][:10] >= day:
            continue
        q[t["symbol"]] = q.get(t["symbol"], 0) + (t["qty"] if t["side"] == "BUY" else -t["qty"])
    return {s: n for s, n in q.items() if n > 0}


def test_day(read_: dict | None, trades: list[dict], times: list[str], bars: dict, market_bars: list, day: str,
             capital: float) -> dict | None:
    """Selling SELL_SHARE of every holding at the day's first open and buying it back at the day's last close,
    against holding (the bot's actual choice), after same-day charges and slippage. None without the day's prices."""
    idx = [i for i, t in enumerate(times) if t.startswith(day)]
    if not idx:
        return None
    i0, i1 = idx[0], idx[-1]
    prev = market_bars[i0 - 1].close if i0 > 0 else None
    o, c = market_bars[i0].open, market_bars[i1].close
    sell = costs.STT_INTRADAY_SELL + costs.EXCHANGE * (1 + costs.GST) + 0.0005
    buy = costs.STAMP_INTRADAY + costs.EXCHANGE * (1 + costs.GST) + 0.0005
    extra = sold = 0.0
    for s, n in held_before(trades, day).items():
        line = bars.get(f"{s}.NS")
        if not line:
            continue
        q = int(n * SELL_SHARE)
        so, sc = line[i0].open, line[i1].close
        sold += q * so
        extra += q * (so * (1 - sell) - sc * (1 + buy))
    return {"read": read_, "flagged": bool(read_ and read_["flagged"]), "signs": read_["signs"] if read_ else None,
            "nifty_gap_pct": round((o / prev - 1) * 100, 2) if prev else None,
            "nifty_open_to_close_pct": round((c / o - 1) * 100, 2),
            "sold_value": round(sold), "extra_rupees": round(extra), "extra_pct": round(extra / capital * 100, 3),
            "day_complete": times[i1][11:] >= "15:15"}


def markdown(t: dict) -> list[str]:
    r = t.get("read")
    L = ["## Pre-open test: sell half at the open on warning signs? (tracked, not traded)", ""]
    if r:
        L.append(f"- Read at {r['at'][11:16]}: " + "; ".join(
            f"{c['name']} {'—' if c['change_pct'] is None else format(c['change_pct'], '+.2f') + '%'}"
            + (" (warning)" if c["sign"] else "") for c in r["cues"]) + ".")
        L.append(f"- {r['signs']} warning sign(s): " + ("FLAGGED (2 or more)." if r["flagged"] else "not flagged."))
    else:
        L.append("- No pre-open read this day (the server was not up between 09:00 and 09:15).")
    gap = "—" if t["nifty_gap_pct"] is None else f"{t['nifty_gap_pct']:+.2f}%"
    L += [f"- NIFTY opened {gap} from yesterday's close and moved {t['nifty_open_to_close_pct']:+.2f}% from the open "
          "to the close.",
          f"- Selling half the shares (Rs {t['sold_value']:,.0f}) at the open and buying them back at the close would "
          f"have made Rs {t['extra_rupees']:+,.0f} ({t['extra_pct']:+.3f}% of the capital) compared with holding, "
          "after charges." + ("" if t["day_complete"] else " The day is not finished."), ""]
    return L
