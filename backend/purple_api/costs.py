"""What the bot's trading would cost in real Indian taxes and charges. Shown apart from returns, never deducted.

The paper portfolio keeps its simple model (fees 3 bps + slippage 5 bps per side, see desk.simulate). This module
estimates the bill a real trader would get for the same trades, so the daily review and the AI manager can see
how much churn costs and work to reduce it.

Rates for NSE equity cash, checked 22 Oct 2026 against broker and tax pages (not official notices; recheck before
relying on them): STT 0.1% on buy and sell for delivery, 0.025% on the sell side for intraday; stamp duty 0.015% of
buys (0.003% intraday); NSE transaction charge ~0.00297%; SEBI fee Rs 10 per crore; GST 18% on brokerage and
exchange/SEBI charges (not on STT or stamp duty); depository charge ~Rs 15.34 per stock sold from the demat per day
(Zerodha-like, incl. GST). Brokerage assumed zero for delivery and intraday (discount broker; set BROKERAGE_BPS
otherwise). Short-term capital gains (held under a year) are taxed at 20%; intraday profit is business income taxed
at the owner's slab rate (30% assumed, the top slab).
"""
from __future__ import annotations

from collections import defaultdict, deque

STT_DELIVERY, STT_INTRADAY_SELL = 0.001, 0.00025
STAMP_DELIVERY, STAMP_INTRADAY = 0.00015, 0.00003
EXCHANGE, SEBI, GST = 0.0000297, 0.000001, 0.18
BROKERAGE_BPS = 0.0
DP_PER_SELL = 15.34
STCG_TAX, INTRADAY_TAX = 0.20, 0.30


def _split_day(trades: list[dict]) -> dict[str, dict]:
    """Per stock for one day: bought/sold quantity and value. The part bought and sold the same day is intraday."""
    out: dict[str, dict] = defaultdict(lambda: {"bq": 0, "bv": 0.0, "sq": 0, "sv": 0.0})
    for t in trades:
        s = out[t["symbol"]]
        if t["side"] == "BUY":
            s["bq"] += t["qty"]
            s["bv"] += t["qty"] * t["price"]
        else:
            s["sq"] += t["qty"]
            s["sv"] += t["qty"] * t["price"]
    return out


def ledger(trades: list[dict]) -> dict[str, dict]:
    """Per day: charges by kind, intraday and delivery value, realised short-term and intraday profit, and the
    estimated tax. Trades are the bot's executed trades (desk.simulate) in time order. Delivery sells are matched to
    earlier buys first in, first out."""
    by_day: dict[str, list[dict]] = defaultdict(list)
    last = ""
    for t in trades:  # crash-guard sales in the bar still forming are timed "now": they belong to the latest day
        last = t["time"][:10] if t["time"][:1].isdigit() else last
        by_day[last].append(t)
    lots: dict[str, deque] = defaultdict(deque)  # symbol -> [qty, price] bought on earlier days
    out = {}
    for day in sorted(by_day):
        c = {"stt": 0.0, "stamp": 0.0, "exchange": 0.0, "sebi": 0.0, "gst": 0.0, "dp": 0.0, "brokerage": 0.0}
        intra_val = deliv_val = st_gain = intra_gain = 0.0
        for sym, s in _split_day(by_day[day]).items():
            bp = s["bv"] / s["bq"] if s["bq"] else 0.0
            sp = s["sv"] / s["sq"] if s["sq"] else 0.0
            m = min(s["bq"], s["sq"])  # squared off the same day: intraday
            if m:
                intra_val += m * (bp + sp)
                intra_gain += m * (sp - bp)
                c["stt"] += m * sp * STT_INTRADAY_SELL
                c["stamp"] += m * bp * STAMP_INTRADAY
            db_q, ds_q = s["bq"] - m, s["sq"] - m  # what is left is delivery
            deliv_val += db_q * bp + ds_q * sp
            c["stt"] += (db_q * bp + ds_q * sp) * STT_DELIVERY
            c["stamp"] += db_q * bp * STAMP_DELIVERY
            if ds_q:
                c["dp"] += DP_PER_SELL
                left = ds_q
                while left and lots[sym]:
                    lot = lots[sym][0]
                    take = min(left, lot[0])
                    st_gain += take * (sp - lot[1])
                    lot[0] -= take
                    left -= take
                    if not lot[0]:
                        lots[sym].popleft()
            if db_q:
                lots[sym].append([db_q, bp])
        turnover = intra_val + deliv_val
        c["exchange"] = turnover * EXCHANGE
        c["sebi"] = turnover * SEBI
        c["brokerage"] = turnover * BROKERAGE_BPS / 10_000
        c["gst"] = (c["exchange"] + c["sebi"] + c["brokerage"]) * GST
        charges = sum(c.values())
        tax = max(0.0, st_gain) * STCG_TAX + max(0.0, intra_gain) * INTRADAY_TAX
        out[day] = {"charges": {k: round(v, 2) for k, v in c.items()}, "charges_total": round(charges, 2),
                    "turnover": round(turnover), "intraday_value": round(intra_val), "delivery_value": round(deliv_val),
                    "short_term_gain": round(st_gain, 2), "intraday_gain": round(intra_gain, 2),
                    "tax": round(tax, 2), "total": round(charges + tax, 2)}
    return out


def summary(trades: list[dict], day: str | None) -> dict:
    """The day's bill and the bill since the start, in rupees."""
    led = ledger(trades)
    keys = ("charges_total", "tax", "total", "turnover", "intraday_value", "short_term_gain", "intraday_gain")
    since = {k: round(sum(d[k] for d in led.values()), 2) for k in keys}
    return {"day": led.get(day or "", None), "since_start": since, "days": len(led)}


def switch_cost_pct() -> float:
    """Taxes and charges (no slippage, no income tax) of selling Rs 100 of one stock held from earlier and buying
    Rs 100 of another, as a percent of Rs 100."""
    side = STT_DELIVERY + EXCHANGE * (1 + GST) + SEBI * (1 + GST)
    return round((2 * side + STAMP_DELIVERY) * 100, 3)
