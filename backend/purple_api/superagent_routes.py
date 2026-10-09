"""HTTP routes for Trading SuperAgent. Only the curated, pre-approved catalog can run here."""
from __future__ import annotations

import re

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import superagent as sa
from .ai.providers import KEY_ENV, OllamaProvider
from .describe import describe, validate
from .engine import bars_hash, run_backtest
from .schema import Strategy
from .store import Store

AI_KINDS = ("ai-team", "ta-original")


class RunIn(BaseModel):
    agent_id: str
    dataset_id: str | None = None
    symbol: str | None = None  # NSE symbol for the original TradingAgents (prices come from Yahoo)
    days: int = Field(5, ge=1, le=sa.MAX_AI_DAYS)
    analyses: list[str] = ["market"]
    engine: str = "local"  # original TradingAgents only: which AI runs it (see superagent.TA_ENGINES)
    confirm_paid: bool = False  # must be true for a paid engine: the user saw the cost estimate and approved it


class PaperIn(BaseModel):
    agent_id: str
    dataset_id: str | None = None
    symbol: str | None = None
    capital: float = Field(100_000, gt=0, le=1e10)
    analyses: list[str] = ["market"]


def register(app: FastAPI, db: Store):
    jobs = sa.Jobs()
    _local: list = []

    def local_ai():
        """The Ollama model behind TradingAgents' 'Local Qwen' engine, even when drafting runs on Gemini."""
        p = app.state.provider
        if getattr(p, "name", "") != "gemini":
            return p
        if not _local:
            _local.append(OllamaProvider())
        return _local[0]

    def browser_keys(request: Request | None) -> dict:
        """Key the person connected in this browser, as the environment variable TradingAgents expects."""
        if request is None:
            return {}
        env = KEY_ENV.get(request.headers.get("x-ai-provider", "").strip().lower())
        key = request.headers.get("x-ai-key", "").strip()
        return {env: key} if env and key else {}

    def default_ta_engine(keys: dict | None = None) -> dict:
        """Gemini Flash when a Google key is set, else local Qwen (used where the user picks no engine)."""
        avail = {e["id"] for e in sa.ta_engines(local_ai().status()["available"], keys) if e["available"]}
        for eid in ("gemini-flash", "local"):
            if eid in avail:
                return sa.ta_engine(eid)
        raise HTTPException(503, "No AI is available for TradingAgents: set GOOGLE_API_KEY or start Ollama.")

    def agent(agent_id: str) -> dict:
        if agent_id.startswith("version:"):  # a saved (immutable) strategy version acts as a rule bot
            v = db.get_version(agent_id[len("version:"):])
            if not v:
                raise HTTPException(404, "Saved strategy version not found")
            s = db.get_strategy(v["strategy_id"])
            title = f"{s['name'] if s else 'Saved strategy'} (version {v['number']})"
            return {"id": agent_id, "kind": "rules", "title": title, "analyses": [],
                    "strategy": Strategy.model_validate(v["body"])}
        a = next((x for x in sa.catalog() if x["id"] == agent_id), None)
        if not a:
            raise HTTPException(404, "Unknown agent")
        if not a["available"]:
            raise HTTPException(409, f"{a['title']} can't run yet: {a['fidelity']}")
        out = {"id": a["id"], "kind": a["kind"], "title": a["title"], "analyses": a["analyses"]}
        if a["kind"] == "rules":
            out["strategy"] = sa.rule_strategy(a["id"])
        return out

    def check_analyses(a: dict, chosen: list[str]) -> list[str]:
        if a["kind"] not in AI_KINDS:
            return []
        ok = {x["id"] for x in a["analyses"] if x["available"]}
        bad = [c for c in chosen if c not in ok]
        if bad or not chosen:
            raise HTTPException(422, f"Choose from the available analyses: {', '.join(sorted(ok))}.")
        return [x["id"] for x in a["analyses"] if x["id"] in chosen]  # catalog order

    def model_or_503() -> str:
        p = app.state.provider
        if not p.status()["available"]:
            raise HTTPException(503, "The local AI is offline, so AI agents can't run. Rule bots still work.")
        return p.model

    def team_complete():
        p = app.state.provider
        return lambda system, user: p.complete(system, [{"role": "user", "content": user}])

    def rules_ready(st: Strategy, n_bars: int):
        v = validate(st)
        hard = [e for e in v["errors"] if "open question" not in e]
        if hard:
            raise HTTPException(409, {"errors": hard})
        if n_bars <= v["warmup_bars"] + 1:
            raise HTTPException(409, {"errors": [f"Dataset has {n_bars} rows but these rules need {v['warmup_bars']} days of warm-up plus one more."]})

    def store_prices(symbol: str) -> dict:
        """Download daily prices through TradingAgents' Yahoo connection and keep them as a dataset."""
        try:
            bars = sa.ta_prices(symbol)
        except RuntimeError as e:
            raise HTTPException(502, f"Couldn't download prices for {sa.nse_ticker(symbol)}: {e}") from e
        h = bars_hash(bars)
        existing = db.find_dataset_by_hash(h)
        if existing:
            return existing
        ticker = sa.nse_ticker(symbol)
        return db.add_dataset(f"{ticker} · {bars[0].date} → {bars[-1].date}", ticker,
                              "Yahoo Finance via yfinance (unofficial; not verified against NSE)", bars, h)

    def ta_engine_or_error(engine_id: str, confirm_paid: bool, keys: dict) -> dict:
        e = sa.ta_engine(engine_id)
        if not e:
            raise HTTPException(422, f"Unknown AI engine {engine_id!r}.")
        info = next(x for x in sa.ta_engines(local_ai().status()["available"], keys) if x["id"] == e["id"])
        if not info["available"]:
            raise HTTPException(503, f"{e['label']} can't run: {info['why']}")
        if e["paid"] and not confirm_paid:
            raise HTTPException(402, f"{e['label']} costs money per run. Confirm the cost estimate to continue.")
        return e

    def decider(a: dict, bars, symbol: str, analyses: list[str], engine: dict | None = None, keys: dict | None = None):
        if a["kind"] == "ta-original":
            return sa.ta_decider(bars, symbol, analyses, local_ai().model, engine, keys)
        return sa.team_decider(bars, symbol, team_complete())

    @app.get("/api/superagent/agents")
    def agents(request: Request):
        out = []
        for a in sa.catalog():
            a = dict(a)
            if a.get("strategy"):
                a["describe"] = describe(Strategy.model_validate(a["strategy"]))
            if a["kind"] == "ta-original":
                a["engines"] = sa.ta_engines(local_ai().status()["available"], browser_keys(request))
            out.append(a)
        return out

    @app.post("/api/superagent/run")
    def run(body: RunIn, request: Request):
        keys = browser_keys(request)
        a = agent(body.agent_id)
        analyses = check_analyses(a, body.analyses)
        engine = None
        if a["kind"] == "ta-original":
            engine = ta_engine_or_error(body.engine, body.confirm_paid, keys)
            if not body.symbol:
                raise HTTPException(422, "Enter an NSE symbol, e.g. RELIANCE.")
            if body.days > sa.TA_MAX_DAYS:
                raise HTTPException(422, f"The original TradingAgents takes many minutes per day; choose at most {sa.TA_MAX_DAYS} days.")
            meta = store_prices(body.symbol)
            did = meta["id"]
        else:
            did = body.dataset_id
            meta = db.get_dataset_meta(did) if did else None
        bars = db.get_bars(did) if did else None
        if bars is None or meta is None:
            raise HTTPException(404, "Dataset not found")

        if a["kind"] == "rules":
            st = a["strategy"]
            rules_ready(st, len(bars))
            res = run_backtest(st, bars)
            res.update(dataset=meta, describe=describe(st), mode="draft")
            return {"kind": "rules", "result": res, "strategy": st.model_dump()}

        if engine and engine["id"] != "local":
            model = f"{engine['id']}:{engine['quick']}/{engine['deep']}"  # separate decision cache per cloud engine
        elif engine:
            model = local_ai().model  # availability already checked by ta_engine_or_error
        else:
            model = model_or_503()
        if len(bars) < body.days + 30:
            raise HTTPException(409, "Not enough price history for that many days.")
        start = len(bars) - body.days
        symbol = meta["symbol"] or "the stock"
        key = f"bt:{a['id']}:{model}:{','.join(analyses)}:{did}:{bars[start].date}"
        cached = db.get_decisions(key)
        missing = sum(1 for b in bars[start:] if b.date not in cached)
        decide = decider(a, bars, symbol, analyses, engine, keys)

        def work(log, progress):
            ds = sa.decide_days(bars, start, cached, decide, log, progress,
                                save=lambda d, p: db.save_decision(key, d, p))
            res = sa.simulate_decisions(bars, start, ds, 100_000, a["title"])
            res["dataset"] = meta
            res["decisions"] = [{"date": b.date, "close": b.close, **ds[b.date]} for b in bars[start:] if b.date in ds]
            return res

        return {"kind": "job", "job": jobs.start(work, missing)}

    @app.get("/api/superagent/jobs/{jid}")
    def job(jid: str):
        j = jobs.get(jid)
        if not j:
            raise HTTPException(404, "Job not found (the server may have restarted)")
        return j

    # ----- paper trading -----
    def account_bars(p: dict):
        if p["synthetic"]:
            return sa.paper_bars(True, db.get_bars(p["dataset_id"]) or [], p["sim_days"])
        latest = db.latest_dataset_for(p["symbol"]) if p["symbol"] else None
        return db.get_bars(latest["id"] if latest else p["dataset_id"]) or []

    def paper_view(p: dict) -> dict:
        a = agent(p["agent_id"])
        bars = account_bars(p)
        if p["synthetic"]:
            data_note = "Synthetic prices (not market data). Use 'Next trading day' to move the market forward."
        elif a["kind"] == "ta-original" or (p["symbol"] or "").endswith(".NS"):
            data_note = f"Real {p['symbol']} prices. Use 'Refresh prices' after each trading day to move the account forward."
        else:
            data_note = f"Import a newer CSV for {p['symbol'] or 'this stock'} to move the account forward."
        start = next((i for i, b in enumerate(bars) if b.date >= p["start_date"]), None)
        if start is None:
            raise HTTPException(409, "Price data no longer reaches the account's start date.")
        view = {"account": p, "agent": {"id": a["id"], "title": a["title"], "kind": a["kind"]},
                "latest_date": bars[-1].date, "data_note": data_note, "pending_days": [],
                "can_refresh": not p["synthetic"] and bool(p["symbol"]) and sa.ta_installed()}
        if a["kind"] == "rules":
            st = a["strategy"].model_copy(update={"initial_capital": p["capital"]})
            res = run_backtest(st, bars, trade_from=start)
            view["today"] = sa.rules_signal(st, bars, res)
            view["decisions"] = []
        else:
            ds = db.get_decisions(f"paper:{p['id']}")
            res = sa.simulate_decisions(bars, start, ds, p["capital"], a["title"])
            view["pending_days"] = [b.date for b in bars[start:] if b.date not in ds]
            view["decisions"] = [{"date": b.date, "close": b.close, **ds[b.date]} for b in bars[start:] if b.date in ds]
            last = ds.get(bars[-1].date)
            view["today"] = ({"date": bars[-1].date, "action": last["action"], "reason": last["reason"]} if last
                             else {"date": bars[-1].date, "action": None, "reason": "The agent hasn't decided today yet."})
        view["result"] = res
        return view

    def paper_or_404(pid: str) -> dict:
        p = db.get_paper(pid)
        if not p:
            raise HTTPException(404, "Paper account not found")
        return p

    @app.get("/api/superagent/paper")
    def list_paper():
        return db.list_paper()

    @app.post("/api/superagent/paper")
    def create_paper(body: PaperIn):
        a = agent(body.agent_id)
        analyses = check_analyses(a, body.analyses)
        if a["kind"] == "ta-original":
            if not body.symbol:
                raise HTTPException(422, "Enter an NSE symbol, e.g. RELIANCE.")
            meta = store_prices(body.symbol)
        else:
            meta = db.get_dataset_meta(body.dataset_id) if body.dataset_id else None
        bars = db.get_bars(meta["id"]) if meta else None
        if not meta or not bars:
            raise HTTPException(404, "Dataset not found")
        if a["kind"] == "rules":
            rules_ready(a["strategy"], len(bars))
        name = f"{a['title']} · {meta['symbol'] or meta['name']}"
        p = db.add_paper(name[:120], a["id"], meta["id"], meta["symbol"], bool(meta["synthetic"]),
                         bars[-1].date, body.capital, analyses)
        return paper_view(p)

    @app.get("/api/superagent/paper/{pid}")
    def get_paper(pid: str):
        return paper_view(paper_or_404(pid))

    @app.post("/api/superagent/paper/{pid}/next-day")
    def next_day(pid: str):
        p = paper_or_404(pid)
        if not p["synthetic"]:
            raise HTTPException(409, "Real-data accounts move forward when prices are refreshed.")
        db.advance_paper(pid)
        return paper_view(db.get_paper(pid))

    @app.post("/api/superagent/paper/{pid}/refresh")
    def refresh(pid: str):
        p = paper_or_404(pid)
        if p["synthetic"] or not p["symbol"]:
            raise HTTPException(409, "Only real-symbol accounts can refresh prices.")
        store_prices(p["symbol"])
        return paper_view(p)

    @app.post("/api/superagent/paper/{pid}/decide")
    def decide(pid: str, request: Request):
        keys = browser_keys(request)
        """Ask the AI agent for every day it hasn't decided yet (background job)."""
        p = paper_or_404(pid)
        v = paper_view(p)
        a = agent(p["agent_id"])
        if a["kind"] not in AI_KINDS:
            raise HTTPException(400, "Rule bots decide instantly; nothing to run.")
        engine = default_ta_engine(keys) if a["kind"] == "ta-original" else None
        if engine is None:
            model_or_503()
        bars = account_bars(p)
        start = next(i for i, b in enumerate(bars) if b.date >= p["start_date"])
        key = f"paper:{pid}"
        cached = db.get_decisions(key)
        analyses = p.get("analyses") or ["market"]
        do = decider(a, bars, p["symbol"] or "the stock", analyses, engine, keys)

        def work(log, progress):
            sa.decide_days(bars, start, cached, do, log, progress, save=lambda d, x: db.save_decision(key, d, x))
            return {"paper_id": pid}

        return {"kind": "job", "job": jobs.start(work, len(v["pending_days"]))}

    @app.delete("/api/superagent/paper/{pid}")
    def delete_paper(pid: str):
        paper_or_404(pid)
        db.delete_paper(pid)
        return {"ok": True}

    # ----- code export -----
    @app.get("/api/superagent/export")
    def export(agent_id: str, symbol: str = "INFY"):
        a = agent(agent_id)
        sym = re.sub(r"[^A-Z0-9&_.-]", "", symbol.upper())[:20] or "INFY"
        slug = re.sub(r"[^a-z0-9]+", "_", a["title"].lower()).strip("_")[:40] or "agent"
        if a["kind"] == "rules":
            code = sa.export_rules(a["strategy"], sym)
        elif a["kind"] == "ta-original":
            code = sa.export_ta(sa.nse_ticker(sym), local_ai().model)
        else:
            code = sa.export_team(sym, app.state.provider.model)
        return {"filename": f"{slug}_{re.sub(r'[^a-z0-9]+', '_', sym.lower())}.py", "code": code}
