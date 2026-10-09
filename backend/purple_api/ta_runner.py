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


def usage_counter():
    """LangChain callback that adds up the token usage every LLM call reports (input/output tokens)."""
    from langchain_core.callbacks import BaseCallbackHandler

    class Usage(BaseCallbackHandler):
        def __init__(self):
            self.totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

        def on_llm_end(self, response, **kwargs):
            self.totals["calls"] += 1
            for gens in response.generations:
                for g in gens:
                    um = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
                    self.totals["input_tokens"] += int(um.get("input_tokens") or 0)
                    self.totals["output_tokens"] += int(um.get("output_tokens") or 0)
    return Usage()


def claude_json_schema_output():
    """Current Claude models reject forced tool calls, LangChain's default way to get structured output.
    Default TradingAgents' structured calls (research manager, trader, portfolio manager) to native JSON-schema output."""
    from tradingagents.llm_clients.anthropic_client import NormalizedChatAnthropic
    base = NormalizedChatAnthropic.with_structured_output

    def with_structured_output(self, schema, *, method=None, **kwargs):
        return base(self, schema, method=method or "json_schema", **kwargs)
    NormalizedChatAnthropic.with_structured_output = with_structured_output


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
    p.add_argument("--provider", default="ollama", choices=["ollama", "google", "anthropic"])
    p.add_argument("--model", default="qwen3:8b", help="local Ollama model")
    p.add_argument("--quick", help="cloud model for analysts, debaters and trader")
    p.add_argument("--deep", help="cloud model for research and portfolio managers")
    p.add_argument("--effort", help="Anthropic effort (low/medium/high)")
    p.add_argument("--ollama", default="http://127.0.0.1:11434/v1")
    a = p.parse_args()
    if a.prices:
        return prices(a.ticker, a.prices)

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.agents.rating import run_rating

    cfg = DEFAULT_CONFIG.copy()
    cfg.update(max_debate_rounds=1, max_risk_discuss_rounds=1)
    if a.provider == "ollama":
        cfg.update(llm_provider="ollama", deep_think_llm=a.model, quick_think_llm=a.model, backend_url=a.ollama,
                   temperature=0)
        label = a.model
    else:
        # Cloud: no temperature (current Claude models reject it), the provider's own endpoint, and patient retries
        # because free tiers rate-limit. Only this provider's key reaches this process (Purple strips the rest).
        cfg.update(llm_provider=a.provider, deep_think_llm=a.deep, quick_think_llm=a.quick, backend_url=None,
                   temperature=None, llm_max_retries=8, anthropic_effort=a.effort,
                   max_tokens=16000)  # bounded output keeps non-streaming calls within SDK time limits
        label = a.quick if a.quick == a.deep else f"{a.quick} (analysts) + {a.deep} (managers)"
        if a.provider == "anthropic":
            claude_json_schema_output()
    analysts = [x for x in a.analysts.split(",") if x]
    usage = usage_counter()
    ta = TradingAgentsGraph(selected_analysts=analysts, debug=False, config=cfg, callbacks=[usage])
    emit(event="step", who="setup", text=f"TradingAgents ready: analysts {', '.join(analysts)}, model {label}.")

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
         settings=ta.run_settings(), usage=usage.totals)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 - reported to Purple
        emit(event="error", text=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-3000:])
        sys.exit(1)
