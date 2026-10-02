"""Runs the ORIGINAL TradingAgents (Tauric Research, Apache-2.0) for one ticker and date.

Started by Purple as a separate process with TradingAgents' own Python (purple/external/TradingAgents/.venv),
so its packages never mix with Purple's. Prints one JSON object per line on stdout:
  {"event": "step", "who": "...", "text": "..."}      progress
  {"event": "result", ...}                            final decision and reports
  {"event": "error", "text": "..."}                   failure
This file must not import purple_api.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback

LABELS = {
    "market_report": "Market analyst", "sentiment_report": "Social-sentiment analyst",
    "news_report": "News analyst", "fundamentals_report": "Fundamentals analyst",
    "investment_plan": "Research manager (after bull vs bear debate)",
    "trader_investment_plan": "Trader", "final_trade_decision": "Portfolio manager (after risk debate)",
}
TO_ACTION = {"buy": "BUY", "overweight": "BUY", "sell": "SELL", "underweight": "SELL", "hold": "HOLD"}


def emit(**kw):
    sys.stdout.write(json.dumps(kw) + "\n")
    sys.stdout.flush()


def prices(ticker: str, period: str):
    """Daily OHLCV from Yahoo Finance via yfinance (TradingAgents' own data vendor)."""
    import yfinance as yf
    df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    rows = [[d.strftime("%Y-%m-%d"), round(float(r["Open"]), 2), round(float(r["High"]), 2), round(float(r["Low"]), 2),
             round(float(r["Close"]), 2), float(r["Volume"])]
            for d, r in df.iterrows() if r["Open"] == r["Open"] and r["Close"] == r["Close"]]
    if not rows:
        raise RuntimeError(f"Yahoo Finance returned no daily prices for {ticker}.")
    emit(event="prices", ticker=ticker, bars=rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ticker", required=True)
    p.add_argument("--date")
    p.add_argument("--prices", metavar="PERIOD", help="only download daily prices, e.g. 2y")
    p.add_argument("--analysts", default="market,news")
    p.add_argument("--model", default="qwen3:8b")
    p.add_argument("--ollama", default="http://127.0.0.1:11434/v1")
    a = p.parse_args()
    if a.prices:
        return prices(a.ticker, a.prices)

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.agents.rating import run_rating

    cfg = DEFAULT_CONFIG.copy()
    cfg.update(llm_provider="ollama", deep_think_llm=a.model, quick_think_llm=a.model, backend_url=a.ollama,
               temperature=0, max_debate_rounds=1, max_risk_discuss_rounds=1)
    analysts = [x for x in a.analysts.split(",") if x]
    ta = TradingAgentsGraph(selected_analysts=analysts, debug=False, config=cfg)
    emit(event="step", who="setup", text=f"TradingAgents ready: analysts {', '.join(analysts)}, model {a.model}.")

    state = ta.create_run_state(a.ticker, a.date)
    graph_args = ta.propagator.get_graph_args()
    final, seen = {}, set()
    for _messages, chunk in ta.stream_run(state, **graph_args):
        if not chunk:
            continue
        final.update(chunk)
        for key, label in LABELS.items():
            val = chunk.get(key)
            if val and key not in seen:
                seen.add(key)
                emit(event="step", who=key, text=f"{label} finished.", report=str(val)[:6000])
    ta.record_decision(a.ticker, a.date, final)
    rating = run_rating(final)
    debate = final.get("investment_debate_state") or {}
    emit(event="result", ticker=a.ticker, date=a.date, rating=rating,
         action=TO_ACTION.get(str(rating).lower(), "HOLD"),
         reports={k: str(final.get(k) or "") for k in LABELS},
         bull=str(debate.get("bull_history") or "")[:6000], bear=str(debate.get("bear_history") or "")[:6000],
         settings=ta.run_settings())


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 - reported to Purple
        emit(event="error", text=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-3000:])
        sys.exit(1)
