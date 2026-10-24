"""The coach's bench: backtest one strategy idea on NIFTY before it may enter the strategy lab (see lab.py).

An idea is a small JSON spec built from known parts, so the daily coach can test ideas without writing code:

    {"name": "Hourly trend, bull only", "signal": "supertrend", "params": {"n": 10, "mult": 3},
     "side": "both|long|short", "regime": "any|bull|bear", "day_trade": false}

Signals: supertrend (n, mult), ema_cross (fast, slow), macd (fast, slow, signal), donchian (entry, exit),
rsi_revert (n, low, high), bollinger_revert (n, k), range_filter (n, mult). Regime: bull = NIFTY closed above its
200-day average the day before, bear = below. day_trade: flat at every close (the trading mandate's strictest form).

Three tests, all on NIFTY with futures charges and slippage, signal on a bar's close and fill at the next open:
1. Hourly bars, about 2 years (Yahoo's limit): return per unit of worst fall vs buy-and-hold.
2. Nearby settings (each number x0.7 and x1.4): a real edge survives small changes.
3. Daily bars, about 20 years: the same rule must make money with at least half of buy-and-hold's return per unit
   of worst fall, over bull and bear markets (not possible for day trades: no long intraday history exists).
Verdict: strong (all three), weak (1 and 2 only), fail. Only strong or weak ideas may be proposed for shadow, and the
owner decides. Results go to coach/bench.json (git-ignored; copied to the dataset like the reports).

CLI: python -m purple_api.bench '<spec json>' [--save]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from . import desk, lab, market
from .engine import Bar

SIGNALS = {
    "supertrend": {"n": 10, "mult": 3.0},
    "ema_cross": {"fast": 9, "slow": 21},
    "macd": {"fast": 12, "slow": 26, "signal": 9},
    "donchian": {"entry": 20, "exit": 10},
    "rsi_revert": {"n": 14, "low": 30, "high": 70},
    "bollinger_revert": {"n": 20, "k": 2.0},
    "range_filter": {"n": 100, "mult": 3.0},
}
NEAR = (0.7, 1.4)
NEAR_SHARE = 0.75  # share of nearby settings that must make money
DAILY_SHARE = 0.5  # over 20 years: at least half of buy-and-hold's return per unit of worst fall


# ---------- indicators (plain lists) ----------

def _ema(xs: list[float], n: int) -> list[float]:
    out, a, k = [], None, 2 / (n + 1)
    for x in xs:
        a = x if a is None else a + k * (x - a)
        out.append(a)
    return out


def _rsi(xs: list[float], n: int) -> list[float | None]:
    out, up, dn = [None] * len(xs), 0.0, 0.0
    for i in range(1, len(xs)):
        d = xs[i] - xs[i - 1]
        up += (max(d, 0) - up) / n
        dn += (max(-d, 0) - dn) / n
        if i >= n:
            out[i] = 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)
    return out


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def raw_positions(signal: str, p: dict, bars: list[Bar]) -> list[int]:
    """+1 / 0 / -1 per bar from the signal alone (long and short)."""
    c = [b.close for b in bars]
    n = len(c)
    if signal == "supertrend":
        return lab.supertrend(bars, int(p["n"]), float(p["mult"]))
    if signal == "ema_cross":
        f, s = _ema(c, int(p["fast"])), _ema(c, int(p["slow"]))
        return [0 if i < p["slow"] else _sign(f[i] - s[i]) for i in range(n)]
    if signal == "macd":
        m = [a - b for a, b in zip(_ema(c, int(p["fast"])), _ema(c, int(p["slow"])))]
        sig = _ema(m, int(p["signal"]))
        return [0 if i < p["slow"] + p["signal"] else _sign(m[i] - sig[i]) for i in range(n)]
    if signal == "donchian":
        e, x = int(p["entry"]), int(p["exit"])
        out, s = [0] * n, 0
        for i in range(e, n):
            hi, lo = max(b.high for b in bars[i - e:i]), min(b.low for b in bars[i - e:i])
            xhi, xlo = max(b.high for b in bars[i - x:i]), min(b.low for b in bars[i - x:i])
            if s == 0:
                s = 1 if c[i] > hi else (-1 if c[i] < lo else 0)
            elif s == 1 and c[i] < xlo:
                s = -1 if c[i] < lo else 0
            elif s == -1 and c[i] > xhi:
                s = 1 if c[i] > hi else 0
            out[i] = s
        return out
    if signal == "rsi_revert":
        r = _rsi(c, int(p["n"]))
        out, s = [0] * n, 0
        for i in range(n):
            if r[i] is None:
                continue
            if s == 0:
                s = 1 if r[i] < p["low"] else (-1 if r[i] > p["high"] else 0)
            elif (s == 1 and r[i] > 50) or (s == -1 and r[i] < 50):
                s = 0
            out[i] = s
        return out
    if signal == "bollinger_revert":
        k, m = int(p["n"]), float(p["k"])
        out, s = [0] * n, 0
        for i in range(k - 1, n):
            w = c[i - k + 1:i + 1]
            mid = sum(w) / k
            sd = (sum((v - mid) ** 2 for v in w) / (k - 1)) ** 0.5
            if s == 0:
                s = 1 if c[i] < mid - m * sd else (-1 if c[i] > mid + m * sd else 0)
            elif (s == 1 and c[i] >= mid) or (s == -1 and c[i] <= mid):
                s = 0
            out[i] = s
        return out
    if signal == "range_filter":  # DonovanWall's Range Filter (sold as "Brahmastra" on TradingView)
        per, mult = int(p["n"]), float(p["mult"])
        rng = _ema(_ema([0.0] + [abs(c[i] - c[i - 1]) for i in range(1, n)], per), per * 2 - 1)
        filt, out, up, dn, s = [c[0]], [0] * n, 0, 0, 0
        for i in range(1, n):
            r, prev = rng[i] * mult, filt[-1]
            filt.append(max(prev, c[i] - r) if c[i] > prev else min(prev, c[i] + r))
            up, dn = (up + 1, 0) if filt[i] > filt[i - 1] else ((0, dn + 1) if filt[i] < filt[i - 1] else (up, dn))
            if c[i] > filt[i] and up > 0:
                s = 1
            elif c[i] < filt[i] and dn > 0:
                s = -1
            out[i] = s if i >= per * 2 else 0
        return out
    raise ValueError(f"Unknown signal {signal!r}; choose {', '.join(SIGNALS)}.")


def positions(spec: dict, bars: list[Bar], daily: list[Bar], params: dict | None = None) -> list[int]:
    pos = raw_positions(spec["signal"], params or spec_params(spec), bars)
    side, regime = spec.get("side", "both"), spec.get("regime", "any")
    bear = lab.below_200(daily)
    out = []
    for x, b in zip(pos, bars):
        x = max(x, 0) if side == "long" else (min(x, 0) if side == "short" else x)
        if regime != "any":
            state = bear.get(b.date[:10])
            if state is None or state != (regime == "bear"):
                x = 0
        out.append(x)
    return out


def spec_params(spec: dict) -> dict:
    if spec.get("signal") not in SIGNALS:
        raise ValueError(f"Unknown signal {spec.get('signal')!r}; choose {', '.join(SIGNALS)}.")
    return {**SIGNALS[spec["signal"]], **(spec.get("params") or {})}


def nearby(params: dict) -> list[dict]:
    out = []
    for k, v in params.items():
        for f in NEAR:
            w = v * f
            w = max(2, round(w)) if isinstance(v, int) else round(w, 2)
            if w != v:
                out.append({**params, k: w})
    return out


# ---------- tests ----------

def _score(r: dict) -> float:
    """Return per unit of worst fall (higher is better)."""
    return r["return_pct"] / max(abs(r["max_drawdown_pct"]), 1.0)


def _run(spec: dict, bars: list[Bar], daily: list[Bar], params: dict | None = None) -> dict:
    sim = lab.simulate(bars, positions(spec, bars, daily, params), bars[0].date, 100_000, bool(spec.get("day_trade")))
    years: dict[str, float] = {}
    for e in sim["equity"]:
        years[e["time"][:4]] = e["value"]
    by_year, base = {}, 100_000.0
    for y in sorted(years):
        by_year[y] = round((years[y] / base - 1) * 100, 1)
        base = years[y]
    return {"return_pct": sim["return_pct"], "max_drawdown_pct": sim["max_drawdown_pct"],
            "trades": len(sim["trades"]), "by_year": by_year}


def _hold(bars: list[Bar]) -> dict:
    sim = lab.simulate(bars, [1] * len(bars), bars[0].date, 100_000)
    return {"return_pct": sim["return_pct"], "max_drawdown_pct": sim["max_drawdown_pct"]}


def run(spec: dict, hourly: list[Bar], daily: list[Bar]) -> dict:
    params = spec_params(spec)
    h, h_bh = _run(spec, hourly, daily, params), _hold(hourly)
    near = [{"params": q, **_run(spec, hourly, daily, q)} for q in nearby(params)]
    share = sum(1 for x in near if x["return_pct"] > 0) / len(near) if near else 0.0
    d_bh = _hold(daily)
    d = None if spec.get("day_trade") else _run(spec, daily, daily, params)  # daily bars cannot hold a day trade
    t1 = h["return_pct"] > 0 and _score(h) > _score(h_bh)
    t2 = share >= NEAR_SHARE
    t3 = d is not None and d["return_pct"] > 0 and _score(d) >= DAILY_SHARE * _score(d_bh)
    verdict = "strong" if t1 and t2 and t3 else ("weak" if t1 and t2 else "fail")
    why = []
    why.append(f"Hourly {h['return_pct']:+.1f}% (worst fall {h['max_drawdown_pct']:.1f}%) vs buy-and-hold "
               f"{h_bh['return_pct']:+.1f}% ({h_bh['max_drawdown_pct']:.1f}%): " + ("better" if t1 else "not better")
               + " return per unit of risk.")
    why.append(f"{share:.0%} of {len(near)} nearby settings made money (needs {NEAR_SHARE:.0%}).")
    if d is None:
        why.append("No long intraday history exists for a day-trading rule, so it can be weak at best.")
    else:
        why.append(f"Daily since {daily[0].date[:4]}: {d['return_pct']:+.1f}% (worst fall {d['max_drawdown_pct']:.1f}%) "
                   f"vs buy-and-hold {d_bh['return_pct']:+.1f}% ({d_bh['max_drawdown_pct']:.1f}%): "
                   + ("holds up over bull and bear markets." if t3 else
                      f"less than {DAILY_SHARE:.0%} of buy-and-hold's return per unit of risk, so it fails the long history."))
    return {"spec": {**spec, "params": params}, "tested": datetime.now(market.IST).isoformat(timespec="minutes"),
            "verdict": verdict, "why": why,
            "hourly": {**h, "from": hourly[0].date, "to": hourly[-1].date, "buy_hold": h_bh},
            "nearby": near, "nearby_positive_share": round(share, 2),
            "daily": None if d is None else {**d, "from": daily[0].date, "to": daily[-1].date, "buy_hold": d_bh}}


def load_data() -> tuple[list[Bar], list[Bar]]:
    """About 2 years of hourly NIFTY bars and 20 years of daily bars from Yahoo."""
    hourly = [b for b in market.intraday_bars(desk.MARKET, "60m", "730d") if not b.date.endswith("15:30")]
    daily = market.daily_bars(desk.MARKET, "20y")
    return hourly, daily


def markdown(res: dict) -> str:
    s = res["spec"]
    L = [f"### Bench: {s.get('name') or s['signal']} — {res['verdict'].upper()}", "",
         f"Rule: {s['signal']} {s['params']}, side {s.get('side', 'both')}, regime {s.get('regime', 'any')}"
         + (", day trades only" if s.get("day_trade") else "") + "."] + [f"- {w}" for w in res["why"]]
    L.append("- Hourly by year: " + ", ".join(f"{y} {v:+.1f}%" for y, v in res["hourly"]["by_year"].items()))
    return "\n".join(L) + "\n"


def save(res: dict) -> Path:
    from .coach import coach_dir  # the coach's folder (git-ignored outputs)
    f = coach_dir() / "bench.json"
    rows = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    rows.append({k: v for k, v in res.items() if k != "nearby"} | {"nearby_positive_share": res["nearby_positive_share"]})
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    return f


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    spec = json.loads(argv[0])
    spec_params(spec)
    hourly, daily = load_data()
    res = run(spec, hourly, daily)
    sys.stdout.reconfigure(encoding="utf-8")
    print(markdown(res))
    if "--save" in argv[1:]:
        print(f"Saved to {save(res)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
