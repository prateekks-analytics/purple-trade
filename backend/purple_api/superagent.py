"""Trading SuperAgent: ready-made agents, AI-team backtests (background jobs), paper trading and code export."""
from __future__ import annotations

import inspect
import json
import math
import os
import re
import subprocess
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

from . import agent_core, indicators
from .engine import Bar, _metrics, bars_hash, run_backtest
from .sample import synthetic_bars
from .schema import Strategy

TA_URL = "https://github.com/TauricResearch/TradingAgents"
CREW_URL = "https://github.com/tonykipkemboi/crewAI-examples/tree/main/crews/stock_analysis"
TA_GUIDE = "Rules taken from the indicator guide in TradingAgents' market analyst (Tauric Research)."

AI_COSTS = {"fee_bps": 3, "slippage_bps": 5}
MAX_AI_DAYS = 30


def _ind(name, period):
    return {"kind": "indicator", "name": name, "period": period, "source": "close", "offset": 0}


_CLOSE = {"kind": "price", "field": "close", "offset": 0}


def _const(v):
    return {"kind": "const", "value": v}


RULE_BOTS = {
    "ta-golden-cross": {
        "title": "Golden Cross Trend",
        "tagline": "Ride long trends: buy when SMA 50 crosses above SMA 200, sell on the death cross.",
        "strategy": {"name": "Golden Cross Trend",
                     "entry": {"kind": "cross", "left": _ind("sma", 50), "direction": "above", "right": _ind("sma", 200)},
                     "exit": {"kind": "cross", "left": _ind("sma", 50), "direction": "below", "right": _ind("sma", 200)}},
    },
    "ta-rsi-reversal": {
        "title": "RSI 30/70 Reversal",
        "tagline": "Buy oversold dips when RSI(14) crosses below 30, sell when RSI(14) goes above 70.",
        "strategy": {"name": "RSI 30/70 Reversal",
                     "entry": {"kind": "cross", "left": _ind("rsi", 14), "direction": "below", "right": _const(30)},
                     "exit": {"kind": "compare", "left": _ind("rsi", 14), "op": ">", "right": _const(70)}},
    },
    "ta-macd-momentum": {
        "title": "MACD Momentum",
        "tagline": "Buy when MACD turns positive (EMA 12 crosses above EMA 26), sell when it turns negative.",
        "strategy": {"name": "MACD Momentum",
                     "entry": {"kind": "cross", "left": _ind("ema", 12), "direction": "above", "right": _ind("ema", 26)},
                     "exit": {"kind": "cross", "left": _ind("ema", 12), "direction": "below", "right": _ind("ema", 26)}},
    },
    "ta-ema-momentum": {
        "title": "Fast EMA Momentum + Trend Filter",
        "tagline": "Buy when the close crosses above EMA 10 while above SMA 50; sell when it crosses back below EMA 10.",
        "strategy": {"name": "Fast EMA Momentum + Trend Filter",
                     "entry": {"kind": "all", "items": [
                         {"kind": "cross", "left": _CLOSE, "direction": "above", "right": _ind("ema", 10)},
                         {"kind": "compare", "left": _CLOSE, "op": ">", "right": _ind("sma", 50)}]},
                     "exit": {"kind": "cross", "left": _CLOSE, "direction": "below", "right": _ind("ema", 10)}},
    },
}

ANALYSES = [
    {"id": "market", "label": "Market / technical analysis", "available": True,
     "detail": "SMA 50/200, EMA 10, MACD, RSI, Bollinger, ATR, VWMA from the price data."},
    {"id": "news", "label": "News analysis", "available": False,
     "detail": "Needs a news feed. Not connected yet (needs your approval to add a data source)."},
    {"id": "fundamentals", "label": "Fundamentals analysis", "available": False,
     "detail": "Needs company financials. Not connected yet."},
    {"id": "sentiment", "label": "Social sentiment analysis", "available": False,
     "detail": "Needs a social-media feed. Not connected yet."},
]


def catalog() -> list[dict]:
    installed = ta_installed()
    out = [{
        "id": "tradingagents-original", "kind": "ta-original", "title": "TradingAgents (original)",
        "tagline": "The real multi-agent framework: market, news, sentiment and fundamentals analysts → bull vs bear "
                   "debate → trader → risk debate → portfolio manager. Real NSE data from Yahoo Finance.",
        "source": {"name": "TradingAgents v0.5.2 by Tauric Research (Apache-2.0)", "url": TA_URL},
        "fidelity": ("Original TradingAgents code, reviewed and approved, running in its own environment on the AI you "
                     "choose (local by default). Macro data (FRED) is skipped: no API key."
                     if installed else "Not installed on this computer."),
        "analyses": TA_ANALYSES, "available": installed,
        "speed": "about 10 min per trading day on local Qwen; faster on a cloud AI",
    }, {
        "id": "tradingagents", "kind": "ai-team", "title": "TradingAgents Analyst Team",
        "tagline": "Market analyst → bull vs bear debate → trader & risk manager decide BUY / SELL / HOLD each day.",
        "source": {"name": "TradingAgents by Tauric Research (Apache-2.0)", "url": TA_URL},
        "fidelity": "Purple's re-implementation of the TradingAgents workflow running on your local AI. "
                    "Not the original code: only the market analyst is available until news/fundamentals data is connected.",
        "analyses": ANALYSES, "available": True, "speed": "about 30-60 s per trading day on local Qwen",
    }]
    for bid, b in RULE_BOTS.items():
        out.append({"id": bid, "kind": "rules", "title": b["title"], "tagline": b["tagline"],
                    "source": {"name": "TradingAgents indicator guide", "url": TA_URL}, "fidelity": TA_GUIDE,
                    "analyses": [], "available": True, "speed": "instant", "strategy": b["strategy"]})
    out.append({
        "id": "crewai-stock-analysis", "kind": "research", "title": "CrewAI Stock Analysis",
        "tagline": "Research crew that reads SEC 10-K/10-Q filings and the web, then writes an investment report.",
        "source": {"name": "crewAI-examples (stock_analysis)", "url": CREW_URL},
        "fidelity": "Not runnable yet: it needs web search and SEC filings (US companies) and makes no trades.",
        "analyses": [], "available": False, "speed": "-",
    })
    return out


def rule_strategy(agent_id: str) -> Strategy | None:
    b = RULE_BOTS.get(agent_id)
    return Strategy.model_validate(b["strategy"]) if b else None


# ---------- AI-team simulation (same timing contract as the rules engine) ----------

def simulate_decisions(bars: list[Bar], start: int, decisions: dict[str, dict], capital: float,
                       name: str) -> dict:
    """Decision on bar t's close fills at bar t+1's open. Bars before `start` are history only."""
    fee, slip = AI_COSTS["fee_bps"] / 10_000, AI_COSTS["slippage_bps"] / 10_000
    cash, pos, pending = capital, None, None
    trades, equity, events = [], [], []
    exposure = 0
    for t in range(start, len(bars)):
        bar = bars[t]
        if pending:
            side, why = pending
            pending = None
            if side == "BUY" and pos is None:
                px = bar.open * (1 + slip)
                qty = math.floor(cash / (px * (1 + fee)))
                if qty >= 1:
                    f = qty * px * fee
                    cash -= qty * px + f
                    pos = {"i": t, "px": px, "qty": qty, "fee": f, "why": why}
                    events.append({"date": bar.date, "type": "buy", "price": round(px, 2), "qty": qty})
                else:
                    events.append({"date": bar.date, "type": "skipped", "detail": f"Not enough cash for 1 share at {px:.2f}"})
            elif side == "SELL" and pos is not None:
                px = bar.open * (1 - slip)
                f = pos["qty"] * px * fee
                cash += pos["qty"] * px - f
                cost = pos["qty"] * pos["px"] + pos["fee"]
                pnl = pos["qty"] * px - f - cost
                trades.append({"entry_date": bars[pos["i"]].date, "entry_price": round(pos["px"], 2),
                               "exit_date": bar.date, "exit_price": round(px, 2), "qty": pos["qty"],
                               "pnl": round(pnl, 2), "pnl_pct": round(pnl / cost * 100, 2),
                               "bars_held": t - pos["i"], "entry_reason": pos["why"], "exit_reason": why,
                               "fees": round(pos["fee"] + f, 2), "open": False})
                events.append({"date": bar.date, "type": "sell", "price": round(px, 2), "qty": pos["qty"]})
                pos = None
        if pos is not None:
            exposure += 1
        d = decisions.get(bar.date)
        if d and t < len(bars) - 1:
            if d["action"] == "BUY" and pos is None:
                pending = ("BUY", f"Team: BUY — {d.get('reason', '')}"[:300])
            elif d["action"] == "SELL" and pos is not None:
                pending = ("SELL", f"Team: SELL — {d.get('reason', '')}"[:300])
        equity.append({"date": bar.date, "equity": round(cash + (pos["qty"] * bar.close if pos else 0), 2),
                       "close": bar.close})
    if pos is not None:
        last = bars[-1]
        cost = pos["qty"] * pos["px"] + pos["fee"]
        mtm = pos["qty"] * last.close - cost
        trades.append({"entry_date": bars[pos["i"]].date, "entry_price": round(pos["px"], 2), "exit_date": None,
                       "exit_price": None, "qty": pos["qty"], "pnl": round(mtm, 2),
                       "pnl_pct": round(mtm / cost * 100, 2), "bars_held": len(bars) - pos["i"],
                       "entry_reason": pos["why"], "exit_reason": "Still open at last bar (marked to close)",
                       "fees": round(pos["fee"], 2), "open": True})
    window = bars[start:]
    closed = [t for t in trades if not t["open"]]
    metrics = _metrics(SimpleNamespace(initial_capital=capital), window, equity, closed, exposure)
    metrics["trades"] = len(closed)
    return {
        "engine": "purple-superagent/1.0", "metrics": metrics, "trades": trades, "events": events,
        "equity": equity, "warmup_bars": 0, "strategy_hash": "ai-team", "data_hash": bars_hash(window),
        "describe": {"entry": name, "exit": name, "entry_lines": [], "exit_lines": [],
                     "execution": "Team decides on each completed daily close; orders fill at the next day's open "
                                  f"with {AI_COSTS['slippage_bps']} bps slippage and {AI_COSTS['fee_bps']} bps fee per side. "
                                  "Long only, whole shares, all-in sizing."},
        "mode": "draft",
    }


def holding_before(bars: list[Bar], start: int, decisions: dict[str, dict], upto: int) -> bool:
    """Position state when deciding on bar `upto` (replays earlier decisions with fills)."""
    holding, pending = False, None
    for t in range(start, upto + 1):
        if pending == "BUY":
            holding = True
        elif pending == "SELL":
            holding = False
        pending = None
        if t == upto:
            return holding
        d = decisions.get(bars[t].date)
        if d and d["action"] == "BUY" and not holding:
            pending = "BUY"
        elif d and d["action"] == "SELL" and holding:
            pending = "SELL"
    return holding


# ---------- background jobs ----------

class Jobs:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, fn, total: int) -> dict:
        jid = uuid.uuid4().hex[:12]
        job = {"id": jid, "status": "running", "done": 0, "total": total, "log": [], "result": None, "error": None}
        with self._lock:
            self._jobs[jid] = job

        def log(kind: str, text: str, date: str | None = None):
            with self._lock:
                job["log"].append({"kind": kind, "text": text, "date": date})

        def progress():
            with self._lock:
                job["done"] += 1

        def run():
            try:
                res = fn(log, progress)
                with self._lock:
                    job["result"], job["status"] = res, "done"
            except Exception as e:  # noqa: BLE001 - reported to the user
                with self._lock:
                    job["error"], job["status"] = f"{type(e).__name__}: {e}", "error"

        threading.Thread(target=run, daemon=True).start()
        return self.get(jid)

    def get(self, jid: str) -> dict | None:
        with self._lock:
            j = self._jobs.get(jid)
            return json.loads(json.dumps(j)) if j else None


def decide_days(bars: list[Bar], start: int, cached: dict[str, dict], decide_one, log, progress,
                save) -> dict[str, dict]:
    """Ask the agent about every bar from `start` that has no cached decision. Sequential: each day's
    position depends on earlier decisions. decide_one(t, holding, log) -> decision dict."""
    decisions = dict(cached)
    for t in range(start, len(bars)):
        date = bars[t].date
        if date in decisions:
            continue
        holding = holding_before(bars, start, decisions, t)
        d = decide_one(t, holding, lambda k, x: log(k, x, date))
        for n in d.get("notes", []):
            log("note", n, date)
        decisions[date] = d
        save(date, d)
        progress()
    return decisions


def team_decider(bars: list[Bar], symbol: str, complete):
    """Purple's re-implemented team (agent_core)."""
    def decide(t, holding, log):
        report = agent_core.market_report(symbol, agent_core.market_snapshot(bars, t))
        log("analyst", report)
        d = agent_core.run_team(report, symbol, holding, complete, on_step=log)
        d["report"] = report
        return d
    return decide


# ---------- the ORIGINAL TradingAgents, run in its own environment ----------

TA_DIR = Path(__file__).resolve().parents[2] / "external" / "TradingAgents"
TA_HOME = TA_DIR.parent / "ta_home"
TA_RUNNER = Path(__file__).with_name("ta_runner.py")
TA_ANALYSES = [
    {"id": "market", "label": "Market / technical analyst", "available": True,
     "detail": "Prices and indicators from Yahoo Finance (stockstats)."},
    {"id": "news", "label": "News analyst", "available": True, "detail": "Company and global news via Yahoo Finance."},
    {"id": "social", "label": "Social-sentiment analyst", "available": True, "detail": "Sentiment from news / social sources."},
    {"id": "fundamentals", "label": "Fundamentals analyst", "available": True,
     "detail": "Financial statements (SEC EDGAR for US, Yahoo for others)."},
]
TA_MAX_DAYS = 5
# Which AI runs the original TradingAgents. Cloud engines get ONLY their own key (set by the user as an environment
# variable before starting Purple); every other *_API_KEY is still stripped. Paid engines need explicit confirmation
# per run. Free-tier limits and prices are third-party / list figures checked 3 Oct 2026 — recheck before relying on them.
TA_ENGINES = [
    {"id": "local", "label": "Local Qwen (free, on this computer)", "provider": "ollama", "key_env": None,
     "paid": False, "quick": None, "deep": None, "minutes": (10, 20),
     "note": "Private and free. 8B model: weaker analysis, ~10 min per day."},
    {"id": "gemini-flash", "label": "Google Gemini Flash (free tier)", "provider": "google", "key_env": "GOOGLE_API_KEY",
     "paid": False, "quick": "gemini-3.8-flash", "deep": "gemini-3.8-flash", "minutes": (2, 10),
     "note": "Free tier: rate-limited (hundreds of requests/day reported); Google may use free-tier prompts to improve "
             "its products. Only public prices/news are sent."},
    {"id": "gemini-pro", "label": "Gemini Pro managers + Flash analysts (free tier)", "provider": "google",
     "key_env": "GOOGLE_API_KEY", "paid": False, "quick": "gemini-3.8-flash", "deep": "gemini-3.1-pro-preview",
     "minutes": (3, 15),
     "note": "Pro's free quota is small (~25–50 requests/day reported) and may not include this preview model; "
             "a run can stop on a quota error."},
    {"id": "claude-opus", "label": "Claude Opus 5.5 (paid API)", "provider": "anthropic", "key_env": "ANTHROPIC_API_KEY",
     "paid": True, "quick": "claude-opus-5-5", "deep": "claude-opus-5-5", "effort": "high", "minutes": (2, 10),
     "cost_per_day": (0.60, 1.00),
     "note": "Billed to Anthropic API credits (not a Claude.ai subscription). Estimate ~$0.60–1.00 per day with "
             "2 analysts at list price $4/$20 per 1M tokens; real usage is shown after each day."},
]


def ta_engine(engine_id: str) -> dict | None:
    return next((e for e in TA_ENGINES if e["id"] == engine_id), None)


def ta_engines(local_ok: bool) -> list[dict]:
    """Engines with availability; never reveals key values, only whether the variable is set."""
    out = []
    for e in TA_ENGINES:
        ok = local_ok if e["key_env"] is None else bool(os.environ.get(e["key_env"]))
        why = "" if ok else ("Local AI is offline." if e["key_env"] is None
                             else f"Set {e['key_env']} in your environment, then restart Purple.")
        out.append({k: e[k] for k in ("id", "label", "paid", "note", "minutes")}
                   | {"cost_per_day": e.get("cost_per_day"), "available": ok, "why": why})
    return out


def ta_engine_args(engine: dict, local_model: str) -> list[str]:
    if engine["provider"] == "ollama":
        return ["--provider", "ollama", "--model", local_model]
    args = ["--provider", engine["provider"], "--quick", engine["quick"], "--deep", engine["deep"]]
    return args + (["--effort", engine["effort"]] if engine.get("effort") else [])


def ta_python() -> Path:
    win = TA_DIR / ".venv" / "Scripts" / "python.exe"
    return win if win.exists() else TA_DIR / ".venv" / "bin" / "python"


def ta_installed() -> bool:
    return ta_python().exists() and (TA_DIR / "tradingagents").is_dir()


def nse_ticker(symbol: str) -> str:
    s = re.sub(r"[^A-Za-z0-9.&^_-]", "", symbol or "").upper()
    return s if "." in s or s.startswith("^") else f"{s}.NS"


def _ta_process(args: list[str], on_event, timeout_s: float) -> dict:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
           "TRADINGAGENTS_RESULTS_DIR": str(TA_HOME / "logs"), "TRADINGAGENTS_CACHE_DIR": str(TA_HOME / "cache"),
           "TRADINGAGENTS_MEMORY_LOG_PATH": str(TA_HOME / "memory" / "trading_memory.md")}
    provider = args[args.index("--provider") + 1] if "--provider" in args else "ollama"
    keep = next((e["key_env"] for e in TA_ENGINES if e["provider"] == provider and e["key_env"]), None)
    for k in [k for k in env if k.endswith("_API_KEY") and k != keep]:
        env.pop(k)  # hand the agent only the key of the engine the user chose for this run, never any other
    proc = subprocess.Popen([str(ta_python()), str(TA_RUNNER), *args], cwd=str(TA_DIR), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace")
    timed_out = threading.Event()

    def kill():
        timed_out.set()
        proc.kill()
    timer = threading.Timer(timeout_s, kill)
    timer.start()
    result, tail = None, []
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                tail = (tail + [line])[-15:]
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event") in ("result", "prices"):
                result = ev
            elif ev.get("event") == "error":
                raise RuntimeError(ev.get("text", "TradingAgents failed"))
            else:
                on_event(ev)
        proc.wait()
    finally:
        timer.cancel()
    if result is None:
        why = f" (stopped after the {timeout_s / 60:.0f}-minute limit)" if timed_out.is_set() else ""
        raise RuntimeError(f"TradingAgents finished without a result{why}"
                           + (": " + " | ".join(tail[-3:]) if tail else "."))
    return result


def ta_prices(symbol: str, period: str = "2y") -> list[Bar]:
    ev = _ta_process(["--ticker", nse_ticker(symbol), "--prices", period], lambda e: None, 180)
    return [Bar(*row) for row in ev["bars"]]


def ta_decider(bars: list[Bar], symbol: str, analysts: list[str], model: str, engine: dict | None = None):
    ticker = nse_ticker(symbol)
    engine = engine or TA_ENGINES[0]

    def decide(t, holding, log):
        def on_event(ev):
            log(ev.get("who", "step"), ev.get("text", ""))
        ev = _ta_process(["--ticker", ticker, "--date", bars[t].date, "--analysts", ",".join(analysts),
                          *ta_engine_args(engine, model)], on_event, 45 * 60)
        action, notes = ev["action"], []
        usage = ev.get("usage") or {}
        if usage.get("calls"):
            notes.append(f"AI: {engine['label']} · {usage['calls']} calls · {usage.get('input_tokens', 0):,} input / "
                         f"{usage.get('output_tokens', 0):,} output tokens.")
        if action == "BUY" and holding:
            action = "HOLD"
            notes.insert(0, f"TradingAgents rated {ev['rating']} while already holding: kept the position.")
        elif action == "SELL" and not holding:
            action = "HOLD"
            notes.insert(0, f"TradingAgents rated {ev['rating']} while flat: no shorting, so no trade.")
        reports = ev.get("reports", {})
        return {"action": action, "confidence": 0.0, "rating": ev["rating"], "engine": engine["id"], "usage": usage,
                "reason": (reports.get("final_trade_decision") or "")[:1500],
                "bull": ev.get("bull", ""), "bear": ev.get("bear", ""), "notes": notes,
                "report": "\n\n".join(f"## {k}\n{v}" for k, v in reports.items() if v)[:20000]}
    return decide


# ---------- code export ----------

def _module_body(mod) -> str:
    src = inspect.getsource(mod)
    src = re.sub(r'^"""(.|\n)*?"""\n', "", src, count=1)
    return "\n".join(l for l in src.splitlines() if not l.startswith(("from __future__", "from .")))


_BROKER = '''
# ---------------------------------------------------------------------------
# Broker hand-off. DRY_RUN = True only prints the order. Nothing is sent until YOU
# switch it off, choose a broker and set your own keys as environment variables.
# The Zerodha Kite Connect call below follows its Python client (pip install kiteconnect);
# check it against the current Kite Connect docs before use (UNVERIFIED by Purple Trade).
# Automated orders by retail traders in India fall under SEBI's algo-trading framework
# (registered broker APIs, possible algo registration). Confirm the rules with your broker.
# ---------------------------------------------------------------------------
DRY_RUN = True
BROKER = "none"          # "zerodha" to use Kite Connect


def place_order(side, qty, symbol):
    if DRY_RUN or BROKER == "none":
        print(f"[DRY RUN] would {side} {qty} x {symbol} at market (NSE, delivery)")
        return None
    if BROKER == "zerodha":
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=os.environ["KITE_API_KEY"])
        kite.set_access_token(os.environ["KITE_ACCESS_TOKEN"])
        return kite.place_order(
            variety=kite.VARIETY_REGULAR, exchange=kite.EXCHANGE_NSE, tradingsymbol=symbol,
            transaction_type=kite.TRANSACTION_TYPE_BUY if side == "BUY" else kite.TRANSACTION_TYPE_SELL,
            quantity=qty, product=kite.PRODUCT_CNC, order_type=kite.ORDER_TYPE_MARKET)
    raise SystemExit(f"Unknown BROKER {BROKER!r}")


class Bar:
    def __init__(self, date, open, high, low, close, volume):
        self.date, self.open, self.high, self.low, self.close, self.volume = date, open, high, low, close, volume


def load_csv(path):
    """CSV with columns date, open, high, low, close[, volume]; ISO dates (YYYY-MM-DD), oldest first."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    norm = [{k.strip().lower(): (v or "").strip().replace(",", "") for k, v in r.items() if k} for r in rows]
    bars = [Bar(r["date"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                float(r.get("volume") or 0)) for r in norm]
    bars.sort(key=lambda b: b.date)
    return bars
'''

_RULES_RUNTIME = '''

def _series(bars, o, cache):
    key = json.dumps(o, sort_keys=True)
    if key not in cache:
        if o["kind"] == "price":
            out = shift([getattr(b, o["field"]) for b in bars], o.get("offset", 0))
        else:
            src = [getattr(b, o.get("source", "close")) for b in bars]
            out = shift(compute(o["name"], src, o["period"]), o.get("offset", 0))
        cache[key] = out
    return cache[key]


def _value(bars, o, t, pos, cache):
    if t < 0:
        return None
    if o["kind"] == "const":
        return o["value"]
    if o["kind"] == "position":
        if pos is None:
            return None
        if o["field"] == "bars_held":
            return float(t - pos["entry_index"] + 1)
        return (bars[t].close / pos["entry_price"] - 1) * 100
    return _series(bars, o, cache)[t]


def evaluate(bars, c, t, pos, cache):
    k = c["kind"]
    if k in ("compare", "cross"):
        a, b = _value(bars, c["left"], t, pos, cache), _value(bars, c["right"], t, pos, cache)
        if k == "compare":
            if a is None or b is None:
                return False
            op = c["op"]
            if op in ("==", "!="):
                eq = round(a, 2) == round(b, 2)
                return eq if op == "==" else not eq
            return {"<": a < b, "<=": a <= b, ">=": a >= b, ">": a > b}[op]
        pa, pb = _value(bars, c["left"], t - 1, pos, cache), _value(bars, c["right"], t - 1, pos, cache)
        if None in (a, b, pa, pb):
            return False
        return (pa <= pb and a > b) if c["direction"] == "above" else (pa >= pb and a < b)
    if k == "all":
        return all(evaluate(bars, i, t, pos, cache) for i in c["items"])
    if k == "any":
        return any(evaluate(bars, i, t, pos, cache) for i in c["items"])
    if k == "not":
        return not evaluate(bars, c["item"], t, pos, cache)
    raise ValueError(k)


def signal(bars, entry_date=None, entry_price=None):
    """BUY / SELL / HOLD for the last completed bar. entry_* describe an open position, if any."""
    t, cache, pos = len(bars) - 1, {}, None
    if entry_date:
        idx = next(i for i, b in enumerate(bars) if b.date >= entry_date)
        pos = {"entry_index": idx, "entry_price": entry_price}
    if pos is None:
        return "BUY" if evaluate(bars, STRATEGY["entry"], t, None, cache) else "HOLD"
    return "SELL" if evaluate(bars, STRATEGY["exit"], t, pos, cache) else "HOLD"


def main():
    p = argparse.ArgumentParser(description=f"{STRATEGY['name']}: signal for the latest daily bar")
    p.add_argument("csv")
    p.add_argument("--symbol", default=SYMBOL)
    p.add_argument("--entry-date", help="date your open position was bought (omit if flat)")
    p.add_argument("--entry-price", type=float)
    p.add_argument("--qty", type=int, default=0, help="shares held (for SELL) or to buy (for BUY)")
    a = p.parse_args()
    bars = load_csv(a.csv)
    s = signal(bars, a.entry_date, a.entry_price)
    print(f"{bars[-1].date} {a.symbol}: {s}")
    if s != "HOLD" and a.qty > 0:
        place_order(s, a.qty, a.symbol)


if __name__ == "__main__":
    main()
'''

_TEAM_RUNTIME = '''

OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL = os.environ.get("PURPLE_AI_MODEL", MODEL_DEFAULT)


def complete(system, user):
    body = json.dumps({"model": MODEL, "stream": False, "think": False, "format": "json",
                       "options": {"temperature": 0, "seed": 42, "num_ctx": 8192},
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["message"]["content"]


def main():
    p = argparse.ArgumentParser(description="AI analyst team: decision for the latest daily bar")
    p.add_argument("csv")
    p.add_argument("--symbol", default=SYMBOL)
    p.add_argument("--holding", action="store_true", help="you currently hold a long position")
    p.add_argument("--qty", type=int, default=0, help="shares to buy / sell if the team acts")
    a = p.parse_args()
    bars = load_csv(a.csv)
    report = market_report(a.symbol, market_snapshot(bars, len(bars) - 1))
    print(report, "\\n")
    d = run_team(report, a.symbol, a.holding, complete, on_step=lambda who, text: print(f"[{who}] {text}\\n"))
    print(f"DECISION {bars[-1].date} {a.symbol}: {d['action']} (confidence {d['confidence']:.0%})")
    for n in d["notes"]:
        print("note:", n)
    if d["action"] != "HOLD" and a.qty > 0:
        place_order(d["action"], a.qty, a.symbol)


if __name__ == "__main__":
    main()
'''


def _header(title: str, extra: str) -> str:
    return (f'"""{title}: exported from Purple Trade (Trading SuperAgent).\n\n'
            f"{extra}\n\n"
            "Usage:  python this_file.py prices.csv --symbol INFY [options]   (python this_file.py -h)\n"
            "Research tool output, not investment advice. Backtests are estimates. You are responsible for any order.\n"
            '"""\nfrom __future__ import annotations\n\nimport argparse\nimport csv\nimport json\nimport os\n'
            "import urllib.request\nfrom typing import Optional, Sequence\n")


def export_rules(strategy: Strategy, symbol: str) -> str:
    return (_header(strategy.name, "Runs the exact rules you tested in Purple Trade on a CSV of daily prices and\n"
                                   "prints BUY / SELL / HOLD for the latest completed day. Fills in Purple's backtest\n"
                                   "assume the next day's open.")
            + f"\nSYMBOL = {symbol!r}\nSTRATEGY = json.loads({json.dumps(json.dumps(strategy.model_dump()))})\n"
            + "\n# ---- indicators (identical to Purple Trade's engine) ----\n"
            + _module_body(indicators) + "\n" + _BROKER + _RULES_RUNTIME)


def export_team(symbol: str, model: str) -> str:
    return (_header("TradingAgents-style analyst team",
                    "Market analyst (deterministic indicators) -> bull vs bear debate -> trader / risk manager,\n"
                    "using a local Ollama model. Workflow modelled on TradingAgents by Tauric Research (Apache-2.0);\n"
                    "this is Purple Trade's re-implementation, not their code. Standard library only.")
            + f"\nSYMBOL = {symbol!r}\nMODEL_DEFAULT = {model!r}\n"
            + "\n# ---- indicators ----\n" + _module_body(indicators)
            + "\n# ---- analyst team ----\n" + _module_body(agent_core).replace("from typing import Callable, Optional, Sequence", "from typing import Callable")
            + "\n" + _BROKER + _TEAM_RUNTIME)


_TA_RUNTIME = '''

RATING_TO_ACTION = {"buy": "BUY", "overweight": "BUY", "sell": "SELL", "underweight": "SELL", "hold": "HOLD"}


def main():
    p = argparse.ArgumentParser(description="Original TradingAgents decision for one NSE stock and date")
    p.add_argument("--symbol", default=SYMBOL, help="Yahoo ticker, e.g. RELIANCE.NS")
    p.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    p.add_argument("--analysts", default="market,news,social,fundamentals")
    p.add_argument("--qty", type=int, default=0, help="shares to buy / sell if it acts")
    a = p.parse_args()
    import datetime
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    cfg = DEFAULT_CONFIG.copy()
    cfg.update(llm_provider="ollama", deep_think_llm=MODEL_DEFAULT, quick_think_llm=MODEL_DEFAULT,
               backend_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"), temperature=0)
    ta = TradingAgentsGraph(selected_analysts=a.analysts.split(","), debug=True, config=cfg)
    date = a.date or datetime.date.today().isoformat()
    state, rating = ta.propagate(a.symbol, date)
    action = RATING_TO_ACTION.get(str(rating).lower(), "HOLD")
    print(f"\\nDECISION {date} {a.symbol}: {rating} -> {action}")
    if action != "HOLD" and a.qty > 0:
        place_order(action, a.qty, a.symbol.split(".")[0])


if __name__ == "__main__":
    main()
'''


def export_ta(symbol: str, model: str) -> str:
    head = _header("TradingAgents (original) runner",
                   "Runs the ORIGINAL TradingAgents (Tauric Research, Apache-2.0) on your local Ollama model and\n"
                   "hands its BUY / SELL to your broker (DRY_RUN by default).\n"
                   "Setup once:  git clone https://github.com/TauricResearch/TradingAgents && cd TradingAgents\n"
                   "             python -m venv .venv && .venv\\\\Scripts\\\\pip install -e .\n"
                   "Then run this file with that .venv's python. Prices and news come from Yahoo Finance.")
    return head + f"\nSYMBOL = {symbol!r}\nMODEL_DEFAULT = {model!r}\n" + _BROKER + _TA_RUNTIME


def rules_signal(strategy: Strategy, bars: list[Bar], result: dict) -> dict:
    """What the rules say on the last completed bar (the order would fill at the next open)."""
    from .engine import _Ctx, _Pos, _reason, evaluate
    ctx, t = _Ctx(bars=bars), len(bars) - 1
    open_t = next((x for x in result["trades"] if x["open"]), None)
    if open_t:
        idx = next(i for i, b in enumerate(bars) if b.date == open_t["entry_date"])
        ctx.pos = _Pos(idx, open_t["entry_price"], open_t["qty"], 0.0, open_t["entry_reason"],
                       t - idx + 1, (bars[t].close / open_t["entry_price"] - 1) * 100)
        hit = evaluate(ctx, strategy.exit, t)
        return {"date": bars[t].date, "action": "SELL" if hit else "HOLD",
                "reason": _reason(ctx, strategy.exit, t) if hit else "Holding: sell rules not met today."}
    hit = evaluate(ctx, strategy.entry, t)
    return {"date": bars[t].date, "action": "BUY" if hit else "HOLD",
            "reason": _reason(ctx, strategy.entry, t) if hit else "Flat: buy rules not met today."}


def paper_bars(synthetic: bool, base: list[Bar], sim_days: int) -> list[Bar]:
    """Synthetic accounts move forward by generating more of the same seeded series (identical prefix)."""
    return synthetic_bars(len(base) + sim_days) if synthetic else base
