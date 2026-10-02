"""HTTP routes for Trading SuperAgent."""
from __future__ import annotations

import re

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import superagent as sa
from .describe import describe, validate
from .engine import run_backtest
from .schema import Strategy
from .store import Store


class RunIn(BaseModel):
    agent_id: str
    dataset_id: str
    days: int = Field(5, ge=1, le=sa.MAX_AI_DAYS)
    analyses: list[str] = ["market"]


class PaperIn(BaseModel):
    agent_id: str
    dataset_id: str
    capital: float = Field(100_000, gt=0, le=1e10)
    analyses: list[str] = ["market"]


def register(app: FastAPI, db: Store):
    jobs = sa.Jobs()

    def agent(agent_id: str) -> dict:
        if agent_id.startswith("strategy:"):
            s = db.get_strategy(agent_id.split(":", 1)[1])
            if not s:
                raise HTTPException(404, "Your agent was not found")
            body = db.get_version(s["versions"][0]["id"])["body"] if s["versions"] else s["draft"]
            if not body:
                raise HTTPException(409, "This agent has no rules yet")
            st = Strategy.model_validate(body)
            return {"id": agent_id, "kind": "rules", "title": s["name"], "strategy": st}
        a = next((x for x in sa.catalog() if x["id"] == agent_id), None)
        if not a:
            raise HTTPException(404, "Unknown agent")
        if not a["available"]:
            raise HTTPException(409, f"{a['title']} can't run yet: {a['fidelity']}")
        out = {"id": a["id"], "kind": a["kind"], "title": a["title"]}
        if a["kind"] == "rules":
            out["strategy"] = sa.rule_strategy(a["id"])
        return out

    def check_analyses(a: dict, chosen: list[str]):
        if a["kind"] != "ai-team":
            return
        ok = {x["id"] for x in sa.ANALYSES if x["available"]}
        bad = [c for c in chosen if c not in ok]
        if bad or not chosen:
            raise HTTPException(422, "Only market analysis is available until a news / fundamentals / sentiment data source is connected.")

    def provider_or_503():
        p = app.state.provider
        if not p.status()["available"]:
            raise HTTPException(503, "The local AI is offline, so the analyst team can't run. Rule bots still work.")
        return lambda system, user: p.complete(system, [{"role": "user", "content": user}])

    def rules_ready(st: Strategy, n_bars: int):
        v = validate(st)
        hard = [e for e in v["errors"] if "open question" not in e]
        if hard:
            raise HTTPException(409, {"errors": hard})
        if n_bars <= v["warmup_bars"] + 1:
            raise HTTPException(409, {"errors": [f"Dataset has {n_bars} rows but these rules need {v['warmup_bars']} days of warm-up plus one more."]})

    @app.get("/api/superagent/agents")
    def agents():
        out = []
        for a in sa.catalog():
            a = dict(a)
            if a.get("strategy"):
                st = Strategy.model_validate(a["strategy"])
                a["describe"] = describe(st)
            out.append(a)
        return out

    @app.post("/api/superagent/run")
    def run(body: RunIn):
        a = agent(body.agent_id)
        check_analyses(a, body.analyses)
        bars = db.get_bars(body.dataset_id)
        if bars is None:
            raise HTTPException(404, "Dataset not found")
        meta = db.get_dataset_meta(body.dataset_id)
        if a["kind"] == "rules":
            st = a["strategy"]
            rules_ready(st, len(bars))
            res = run_backtest(st, bars)
            res.update(dataset=meta, describe=describe(st), mode="draft")
            return {"kind": "rules", "result": res, "strategy": st.model_dump()}

        complete = provider_or_503()
        if len(bars) < body.days + 30:
            raise HTTPException(409, "Not enough price history for that many days.")
        start = len(bars) - body.days
        symbol = meta["symbol"] or "the stock"
        key = f"bt:{a['id']}:{app.state.provider.model}:{body.dataset_id}:{bars[start].date}"
        cached = db.get_decisions(key)
        missing = sum(1 for b in bars[start:] if b.date not in cached)

        def work(log, progress):
            ds = sa.decide_days(bars, start, symbol, cached, complete, log, progress,
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
    def paper_view(p: dict) -> dict:
        a = agent(p["agent_id"])
        if p["synthetic"]:
            base = db.get_bars(p["dataset_id"]) or []
            bars = sa.paper_bars(True, base, p["sim_days"])
            data_note = "Synthetic prices (not market data). Use 'Next trading day' to move the market forward."
        else:
            latest = db.latest_dataset_for(p["symbol"]) if p["symbol"] else None
            did = latest["id"] if latest else p["dataset_id"]
            bars = db.get_bars(did) or []
            data_note = (f"Using your newest {p['symbol']} prices. Import a newer NSE CSV for {p['symbol']} to move the account forward."
                         if p["symbol"] else "Import newer prices to move the account forward.")
        start = next((i for i, b in enumerate(bars) if b.date >= p["start_date"]), None)
        if start is None:
            raise HTTPException(409, "Price data no longer reaches the account's start date.")
        view = {"account": p, "agent": {"id": a["id"], "title": a["title"], "kind": a["kind"]},
                "latest_date": bars[-1].date, "data_note": data_note, "pending_days": []}
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
                             else {"date": bars[-1].date, "action": None, "reason": "The team hasn't decided today yet."})
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
        check_analyses(a, body.analyses)
        meta = db.get_dataset_meta(body.dataset_id)
        bars = db.get_bars(body.dataset_id)
        if not meta or not bars:
            raise HTTPException(404, "Dataset not found")
        if a["kind"] == "rules":
            rules_ready(a["strategy"], len(bars))
        name = f"{a['title']} · {meta['symbol'] or meta['name']}"
        p = db.add_paper(name[:120], a["id"], body.dataset_id, meta["symbol"], bool(meta["synthetic"]),
                         bars[-1].date, body.capital)
        return paper_view(p)

    @app.get("/api/superagent/paper/{pid}")
    def get_paper(pid: str):
        return paper_view(paper_or_404(pid))

    @app.post("/api/superagent/paper/{pid}/next-day")
    def next_day(pid: str):
        p = paper_or_404(pid)
        if not p["synthetic"]:
            raise HTTPException(409, "Real-data accounts move forward only when you import newer prices.")
        db.advance_paper(pid)
        return paper_view(db.get_paper(pid))

    @app.post("/api/superagent/paper/{pid}/decide")
    def decide(pid: str):
        """Ask the AI team for every day it hasn't decided yet (background job)."""
        p = paper_or_404(pid)
        v = paper_view(p)
        if v["agent"]["kind"] != "ai-team":
            raise HTTPException(400, "Rule bots decide instantly; nothing to run.")
        complete = provider_or_503()
        key = f"paper:{pid}"
        bars = (sa.paper_bars(True, db.get_bars(p["dataset_id"]) or [], p["sim_days"]) if p["synthetic"]
                else db.get_bars((db.latest_dataset_for(p["symbol"]) or {"id": p["dataset_id"]})["id"]) if p["symbol"]
                else db.get_bars(p["dataset_id"]))
        start = next(i for i, b in enumerate(bars) if b.date >= p["start_date"])
        cached = db.get_decisions(key)

        def work(log, progress):
            sa.decide_days(bars, start, p["symbol"] or "the stock", cached, complete, log, progress,
                           save=lambda d, x: db.save_decision(key, d, x))
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
        sym = re.sub(r"[^A-Z0-9&_-]", "", symbol.upper())[:20] or "INFY"
        slug = re.sub(r"[^a-z0-9]+", "_", a["title"].lower()).strip("_")[:40] or "agent"
        if a["kind"] == "rules":
            code = sa.export_rules(a["strategy"], sym)
        else:
            code = sa.export_team(sym, app.state.provider.model)
        return {"filename": f"{slug}_{sym.lower()}.py", "code": code}
