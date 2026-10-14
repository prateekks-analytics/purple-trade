"""HTTP routes for Trading SuperAgent. Only the curated, pre-approved catalog can run here."""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import live_agents, market, superagent as sa
from .ai.providers import KEY_ENV, OllamaProvider, ProviderError, make_provider
from .describe import describe, validate
from .engine import bars_hash, run_backtest
from .schema import Strategy
from .store import Store

AI_KINDS = ("ai-team", "ta-original", *sa.NEWS_KINDS)
SYMBOL_KINDS = ("ta-original", *sa.NEWS_KINDS)  # agents that need a real NSE symbol (their data comes from the web)
# bar sizes a paper account can follow, per agent kind (AI agents decide at most every 15 minutes: API limits)
INTERVALS = {"rules": ("1d", "5m", "15m", "30m"), "ai-news": ("1d", "15m", "30m"), "ai-crew": ("1d", "30m"),
             "ai-team": ("1d",), "ta-original": ("1d",)}
FREE_BACKGROUND_AI = ("gemini", "ollama")  # the live loop only calls the server's own free AI, never a browser key


class RunIn(BaseModel):
    agent_id: str
    dataset_id: str | None = None
    symbol: str | None = None  # NSE symbol for the original TradingAgents (prices come from Yahoo)
    days: int = Field(5, ge=1, le=sa.MAX_AI_DAYS)
    analyses: list[str] = ["market"]
    engine: str = "local"  # original TradingAgents only: which AI runs it (see superagent.TA_ENGINES)
    confirm_paid: bool = False  # must be true for a paid engine: the user saw the cost estimate and approved it


class PricesIn(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=30)


class PaperIn(BaseModel):
    agent_id: str
    dataset_id: str | None = None
    symbol: str | None = None
    capital: float = Field(100_000, gt=0, le=1e10)
    analyses: list[str] = ["market"]
    interval: str = "1d"  # "1d" daily, or an intraday bar size such as "5m" (live accounts only)


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

    def ai_for(request: Request | None):
        """The AI connected in this browser (key sent per request, never stored), else the server's default."""
        name = request.headers.get("x-ai-provider", "").strip().lower() if request else ""
        if name:
            try:
                return make_provider(name, request.headers.get("x-ai-key", "").strip(),
                                     request.headers.get("x-ai-model", "").strip())
            except ProviderError as e:
                raise HTTPException(400, str(e)) from e
        return app.state.provider

    def ai_or_503(p):
        if not p.status()["available"]:
            raise HTTPException(503, "No AI is connected, so this agent can't decide. Connect an AI (free Gemini works).")
        return p

    _names: dict[str, str] = {}

    def company(symbol: str) -> str:
        """Company name for news searches (from Yahoo; the symbol itself when unknown)."""
        if symbol not in _names:
            try:
                _names[symbol] = market.quote(symbol).get("name") or symbol.split(".")[0]
            except market.MarketError:
                return symbol.split(".")[0]
        return _names[symbol]

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
        """Download completed daily prices from Yahoo Finance and keep them as a dataset (deduplicated by hash)."""
        try:
            ticker = market.ticker(symbol)
            bars = market.daily_bars(ticker)
        except market.MarketError as e:
            raise HTTPException(502, f"Couldn't download prices for {symbol}: {e}") from e
        h = bars_hash(bars)
        existing = db.find_dataset_by_hash(h)
        if existing:
            return existing
        return db.add_dataset(f"{ticker} · {bars[0].date} → {bars[-1].date}", ticker, market.SOURCE, bars, h)

    # ----- live market data -----
    @app.post("/api/market/prices")
    def market_prices(body: PricesIn):
        return store_prices(body.symbol)

    @app.get("/api/market/quote")
    def market_quote(symbol: str):
        try:
            return market.quote(symbol)
        except market.MarketError as e:
            raise HTTPException(502, str(e)) from e

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

    def decider(a: dict, bars, symbol: str, analyses: list[str], engine: dict | None = None, keys: dict | None = None,
                ai=None):
        if a["kind"] in sa.NEWS_KINDS:
            def complete(system, user):
                return ai.complete(system, [{"role": "user", "content": user}])
            make = live_agents.pulse_decider if a["kind"] == "ai-news" else live_agents.crew_decider
            return make(bars, symbol, company(symbol), analyses, complete)
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
        engine = ai = None
        if a["kind"] in SYMBOL_KINDS:
            if a["kind"] == "ta-original":
                engine = ta_engine_or_error(body.engine, body.confirm_paid, keys)
                if body.days > sa.TA_MAX_DAYS:
                    raise HTTPException(422, f"The original TradingAgents takes many minutes per day; choose at most {sa.TA_MAX_DAYS} days.")
            else:
                ai = ai_or_503(ai_for(request))
            if not body.symbol:
                raise HTTPException(422, "Enter an NSE symbol, e.g. RELIANCE.")
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

        if ai is not None:
            model = f"{ai.name}:{ai.model}"
        elif engine and engine["id"] != "local":
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
        decide = decider(a, bars, symbol, analyses, engine, keys, ai)

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

    def fetch_intraday(symbol: str, interval: str, range_: str) -> int:
        try:
            return db.upsert_bars(symbol, interval, market.intraday_bars(symbol, interval, range_))
        except market.MarketError as e:
            raise HTTPException(429 if isinstance(e, market.RateLimited) else 502,
                                f"Couldn't download {interval} prices for {symbol}: {e}") from e

    # ----- live loop: keeps live paper accounts moving while the server runs -----
    loop = {"last_tick": None, "last_error": None, "updated": 0, "decided": 0, "daily_done": set()}
    busy: set[str] = set()

    def session_state(now: datetime) -> str:
        ist = now.astimezone(market.IST)
        if ist.weekday() >= 5:
            return "closed"
        hm = (ist.hour, ist.minute)
        return "open" if (9, 15) <= hm < (15, 45) else "after" if hm >= market.SETTLED else "closed"

    def tick(now: datetime | None = None) -> dict:
        """One pass: fetch new intraday bars during the session, the day's close after 16:00 IST, and let the
        server's own free AI decide pending bars of news agents. Errors are recorded, never raised."""
        now = now or datetime.now(market.IST)
        state = session_state(now)
        day = now.astimezone(market.IST).date().isoformat()
        accounts = [p for p in db.list_paper() if live_symbol(p)]
        done: set = set()
        for p in accounts:
            try:
                if intraday(p) and state in ("open", "after") and (p["symbol"], p["interval"]) not in done:
                    done.add((p["symbol"], p["interval"]))
                    loop["updated"] += db.upsert_bars(p["symbol"], p["interval"],
                                                      market.intraday_bars(p["symbol"], p["interval"], "1d"))
                elif not intraday(p) and state == "after" and (day, p["symbol"]) not in loop["daily_done"]:
                    store_prices(p["symbol"])
                    loop["daily_done"].add((day, p["symbol"]))
            except (market.MarketError, HTTPException) as e:
                loop["last_error"] = str(getattr(e, "detail", None) or e)
                if isinstance(e, market.RateLimited) or "limiting" in loop["last_error"]:
                    break
        ai = app.state.provider
        if getattr(ai, "name", "") in FREE_BACKGROUND_AI:
            for p in accounts:
                a = next((x for x in sa.catalog() if x["id"] == p["agent_id"]), None)
                if not a or a["kind"] not in sa.NEWS_KINDS or p["id"] in busy:
                    continue
                bars = account_bars(p)
                start = next((i for i, b in enumerate(bars) if b.date >= p["start_date"]), None)
                key = f"paper:{p['id']}"
                cached = db.get_decisions(key)
                if start is None or all(b.date in cached for b in bars[start:]) or not ai.status()["available"]:
                    continue
                busy.add(p["id"])
                try:
                    do = decider(a, bars, p["symbol"], p.get("analyses") or ["google"], ai=ai)
                    ds = sa.decide_days(bars, start, cached, do, lambda *x: None, lambda: None,
                                        save=lambda d, x, k=key: db.save_decision(k, d, x))
                    loop["decided"] += len(ds) - len(cached)
                except Exception as e:  # noqa: BLE001 - AI/network failures are reported in the status
                    loop["last_error"] = f"{a['title']}: {type(e).__name__}: {e}"
                finally:
                    busy.discard(p["id"])
        loop["last_tick"] = now.isoformat(timespec="seconds")
        return {"session": state, "accounts": len(accounts)}

    app.state.live_tick = tick

    @app.get("/api/market/status")
    def market_status():
        intr = sum(1 for p in db.list_paper() if live_symbol(p) and intraday(p))
        prov = app.state.provider
        return {**market.status(), "session": session_state(datetime.now(market.IST)),
                "loop": {"last_tick": loop["last_tick"], "last_error": loop["last_error"],
                         "bars_saved": loop["updated"], "ai_decisions": loop["decided"], "intraday_accounts": intr,
                         "background_ai": getattr(prov, "name", "") in FREE_BACKGROUND_AI}}

    # ----- paper trading -----
    def intraday(p: dict) -> bool:
        return (p.get("interval") or "1d") != "1d"

    def account_bars(p: dict):
        if intraday(p):
            return db.get_market_bars(p["symbol"], p["interval"])
        if p["synthetic"]:
            return sa.paper_bars(True, db.get_bars(p["dataset_id"]) or [], p["sim_days"])
        latest = db.latest_dataset_for(p["symbol"]) if p["symbol"] else None
        return db.get_bars(latest["id"] if latest else p["dataset_id"]) or []

    def live_symbol(p: dict) -> bool:
        """Real-symbol accounts whose prices come from (or can come from) Yahoo Finance."""
        s = p["symbol"] or ""
        return not p["synthetic"] and (s.endswith(".NS") or s.endswith(".BO") or s.startswith("^"))

    def paper_view(p: dict) -> dict:
        a = agent(p["agent_id"])
        bars = account_bars(p)
        if p["synthetic"]:
            data_note = "Synthetic prices (not market data). Use 'Next trading day' to move the market forward."
        elif intraday(p):
            data_note = (f"Live {p['symbol']} {p['interval']} bars from Yahoo Finance (about 15 minutes delayed). While NSE is "
                         "open, Purple fetches each finished bar every minute, even with this page closed; the bot decides "
                         "on the bar's close and trades at the next bar's open.")
        elif live_symbol(p):
            data_note = (f"Real {p['symbol']} prices from Yahoo Finance (delayed). The account moves forward on its own "
                         "after each NSE session closes; the bot decides on the close and trades at the next open.")
        else:
            data_note = f"Import a newer CSV for {p['symbol'] or 'this stock'} to move the account forward."
        start = next((i for i, b in enumerate(bars) if b.date >= p["start_date"]), None)
        if start is None:
            raise HTTPException(409, "Price data no longer reaches the account's start date.")
        view = {"account": p, "agent": {"id": a["id"], "title": a["title"], "kind": a["kind"]}, "interval": p.get("interval") or "1d",
                "latest_date": bars[-1].date, "data_note": data_note, "pending_days": [],
                "can_refresh": live_symbol(p)}
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
        allowed = INTERVALS.get(a["kind"], ("1d",))
        if body.interval not in allowed:
            raise HTTPException(422, f"{a['title']} can follow these bar sizes: {', '.join(allowed)}.")
        if (a["kind"] in SYMBOL_KINDS or body.interval != "1d") and not body.symbol:
            raise HTTPException(422, "Enter an NSE symbol, e.g. RELIANCE.")
        if body.symbol:  # live account: start from the latest completed session on Yahoo Finance
            meta = store_prices(body.symbol)
        else:
            meta = db.get_dataset_meta(body.dataset_id) if body.dataset_id else None
        bars = db.get_bars(meta["id"]) if meta else None
        if not meta or not bars:
            raise HTTPException(404, "Dataset not found")
        if body.interval != "1d":
            fetch_intraday(meta["symbol"], body.interval, market.INTRADAY_RANGE)
            bars = db.get_market_bars(meta["symbol"], body.interval)
            if len(bars) < 2:
                raise HTTPException(409, f"Yahoo Finance returned no {body.interval} bars for {meta['symbol']}.")
        if a["kind"] == "rules":
            rules_ready(a["strategy"], len(bars))
        every = "" if body.interval == "1d" else f" · {body.interval}"
        name = f"{a['title']} · {meta['symbol'] or meta['name']}{every}"
        p = db.add_paper(name[:120], a["id"], meta["id"], meta["symbol"], bool(meta["synthetic"]),
                         bars[-1].date, body.capital, analyses, body.interval)
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
        if not live_symbol(p):
            raise HTTPException(409, "Only accounts on a real NSE symbol can fetch live prices.")
        if intraday(p):
            fetch_intraday(p["symbol"], p["interval"], "5d")
        else:
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
        ai = ai_or_503(ai_for(request)) if a["kind"] in sa.NEWS_KINDS else None
        if engine is None and ai is None:
            model_or_503()
        bars = account_bars(p)
        start = next(i for i, b in enumerate(bars) if b.date >= p["start_date"])
        key = f"paper:{pid}"
        cached = db.get_decisions(key)
        analyses = p.get("analyses") or ["market"]
        do = decider(a, bars, p["symbol"] or "the stock", analyses, engine, keys, ai)

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
