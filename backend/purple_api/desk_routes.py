"""HTTP routes and the live loop of the portfolio bot (see desk.py). One bot runs at a time."""
from __future__ import annotations

import json
import threading
import time
from collections import Counter
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import desk, market, news
from .store import Store

COMPANY = {"RELIANCE.NS": "Reliance Industries", "HDFCBANK.NS": "HDFC Bank", "ICICIBANK.NS": "ICICI Bank",
           "INFY.NS": "Infosys", "TCS.NS": "Tata Consultancy Services", "BHARTIARTL.NS": "Bharti Airtel",
           "ITC.NS": "ITC", "LT.NS": "Larsen & Toubro", "SBIN.NS": "State Bank of India", "AXISBANK.NS": "Axis Bank"}
SYMBOLS = desk.UNIVERSE + [desk.MARKET]
MOOD_EVERY = 2 * 3600  # seconds between news and social mood reads during the session
BACKTEST_TTL = 6 * 3600


class StartIn(BaseModel):
    capital: float = Field(500_000, ge=10_000, le=1e9)
    days: int = Field(7, ge=0, le=365)  # trading days; 0 = until stopped


def inr(v: float) -> str:
    """12,34,567 (Indian digit grouping)."""
    n = str(int(round(v)))
    head, tail = n[:-3], n[-3:]
    while len(head) > 2:
        tail, head = head[-2:] + "," + tail, head[:-2]
    return f"{head},{tail}" if head else tail


def _ist(t: str) -> datetime:
    return datetime.strptime(t, "%Y-%m-%d %H:%M").replace(tzinfo=market.IST)


def next_bar_close(now: datetime) -> datetime:
    """When the next 30-minute bar completes (bars start 09:15 ... 15:15 IST, weekdays; holidays not checked)."""
    ist = now.astimezone(market.IST)
    day = ist.replace(second=0, microsecond=0)
    for _ in range(8):
        if day.weekday() < 5:
            for k in range(desk.BARS_PER_DAY):
                end = day.replace(hour=9, minute=15) + timedelta(minutes=30 * (k + 1))
                if end > ist:  # Yahoo counts a bar as complete 30 minutes after it starts, 15:15 included
                    return end
        day = (day + timedelta(days=1)).replace(hour=0, minute=0)
        ist = day
    return day


def register(app: FastAPI, db: Store):
    state = {"fetched": {}, "last_error": None, "busy": False, "mood_at": {}, "lessons_done": set(),
             "backtest": None}
    lock = threading.Lock()

    def ai():
        p = app.state.provider
        return p if getattr(p, "name", "") in ("gemini", "ollama") and p.status()["available"] else None

    # ----- data -----
    def fetch(range_: str, max_age: float) -> None:
        """Download 30-minute bars for the basket and NIFTY 50 at most every `max_age` seconds per range."""
        with lock:
            if time.time() - state["fetched"].get(range_, 0) < max_age:
                return
            state["fetched"][range_] = time.time()
            _download(range_)

    def _download(range_: str) -> None:
        for s in SYMBOLS:
            try:
                db.upsert_bars(s, desk.INTERVAL, market.intraday_bars(s, desk.INTERVAL, range_))
            except market.MarketError as e:
                state["last_error"] = f"{desk.short(s)}: {e}"
                if isinstance(e, market.RateLimited):
                    break

    def panel() -> desk.Panel:
        mkt = db.get_market_bars(desk.MARKET, desk.INTERVAL)
        if len(mkt) < 60:
            raise HTTPException(503, "Not enough 30-minute prices yet. Check the internet connection and try again.")
        return desk.align({s: db.get_market_bars(s, desk.INTERVAL) for s in desk.UNIVERSE}, mkt)

    def stale(p: desk.Panel, now: datetime) -> bool:
        """True when a newer bar than the newest stored one has completed."""
        return next_bar_close(_ist(p.times[-1]) + timedelta(minutes=30)) <= now.astimezone(market.IST)

    # ----- the bot's memory -----
    def moods(bot: dict) -> dict[str, dict]:
        return db.get_decisions(f"deskmood:{bot['id']}")

    def mood_index(p: desk.Panel, ms: dict[str, dict]) -> dict[int, dict[str, float]]:
        out = {}
        for ts, m in ms.items():
            i = max((i for i, t in enumerate(p.times) if t <= ts), default=None)
            if i is not None:
                out[i] = {s: v["score"] for s, v in m["scores"].items()}
        return out

    def lessons(bot: dict) -> list[str]:
        return [x for d in db.get_decisions(f"desklesson:{bot['id']}").values() for x in d.get("lessons", [])]

    def read_mood(bot: dict, p: desk.Panel, now: datetime) -> None:
        """Headlines and trader posts for every stock, scored by one AI call. Kept per bar time."""
        prov = ai()
        if not prov:
            return
        blocks = []
        for s in desk.UNIVERSE:
            got = news.headlines(COMPANY[s], s, ["google", "reddit"], limit=6)
            titles = [i["title"] for i in got["items"]][:6]
            blocks.append(f"{desk.short(s)} ({COMPANY[s]}): " + (" | ".join(titles) or "no recent items"))
        raw = prov.complete(desk.MOOD_SYSTEM, [{"role": "user", "content": "<data>\n" + "\n".join(blocks) + "\n</data>"}])
        scores = desk.parse_mood(raw)
        if scores:
            db.save_decision(f"deskmood:{bot['id']}", p.times[-1], {"scores": scores, "at": now.isoformat(timespec="minutes")})
        state["mood_at"][bot["id"]] = time.time()

    # ----- one decision -----
    def run_book(bot: dict, p: desk.Panel) -> tuple[dict, int, dict]:
        start = p.times.index(bot["start_time"]) if bot["start_time"] in p.times else \
            next((i for i, t in enumerate(p.times) if t >= bot["start_time"]), len(p) - 1)
        ds = db.get_decisions(f"desk:{bot['id']}")
        idx = {t: i for i, t in enumerate(p.times)}
        targets = {idx[t]: d["targets"] for t, d in ds.items() if t in idx}
        notes = {idx[t]: d["winner"] for t, d in ds.items() if t in idx}
        return desk.simulate(p, targets, bot["capital"], start, notes), start, ds

    def decide(bot: dict, p: desk.Panel, t: int) -> dict:
        s0 = max(0, t - desk.RECORD_BARS - 3 * desk.BARS_PER_DAY)
        sh = desk.shadows(p, bot["capital"], mood_index(p, moods(bot)), start=s0)
        props = {a: sh["agents"][a]["proposals"][t] for a in desk.AGENT_IDS}
        recs = {a: desk.record(sh["agents"][a]["sim"], s0, t) for a in desk.AGENT_IDS}
        book, _, ds = run_book(bot, p)
        prev = ds[max(ds)]["winner"] if ds else None
        ms = moods(bot)
        mood = ms[max(ms)]["scores"] if ms else None
        out = {"time": p.times[t], "records": {a: None if r is None else round(r * 100, 2) for a, r in recs.items()},
               "proposals": {a: {desk.short(s): w for s, w in v.items()} for a, v in props.items()}}
        prov = ai()
        if prov:
            try:
                prompt = desk.chief_prompt(p.times[t], props, recs, book["holdings"], book["equity"][-1]["value"],
                                           sh["market"], t, mood, lessons(bot))
                got = desk.parse_chief(prov.complete(desk.CHIEF_SYSTEM, [{"role": "user", "content": prompt}]), props)
                return {**out, **got, "by": f"{prov.name}:{prov.model}"}
            except Exception as e:  # noqa: BLE001 - any AI failure falls back to the track record
                state["last_error"] = f"AI chief: {type(e).__name__}: {str(e)[:160]}"
        win = desk.judge(sh, s0, t, prev)
        name = next(a["name"] for a in desk.AGENTS if a["id"] == win)
        return {**out, "winner": win, "targets": props[win], "debate": [], "confidence": None, "by": "record",
                "reason": f"No AI answered, so the desk followed {name}, the agent with the best two-day record."}

    def step(bot: dict, now: datetime, force: bool = False) -> bool:
        """Decide the newest completed bar if it has no decision yet. Older missed bars are skipped (held)."""
        p = panel()
        t = len(p) - 1
        if p.times[t] < bot["start_time"]:
            return False
        key = f"desk:{bot['id']}"
        if p.times[t] in db.get_decisions(key) or finished(bot, p):
            return False
        if ai() and (force or time.time() - state["mood_at"].get(bot["id"], 0) > MOOD_EVERY):
            try:
                read_mood(bot, p, now)
            except Exception as e:  # noqa: BLE001
                state["last_error"] = f"News mood: {type(e).__name__}: {str(e)[:160]}"
                state["mood_at"][bot["id"]] = time.time()
        db.save_decision(key, p.times[t], decide(bot, p, t))
        return True

    def learn(bot: dict, p: desk.Panel, day: str) -> None:
        """After the close: one AI call turns today's results into lessons for tomorrow."""
        prov = ai()
        ds = {t: d for t, d in db.get_decisions(f"desk:{bot['id']}").items() if t.startswith(day)}
        if not prov or not ds:
            return
        book, start, _ = run_book(bot, p)
        eq = [e for e in book["equity"] if e["time"].startswith(day)]
        mk = [b for b in p.market if b.date.startswith(day)]
        wins = Counter(d["winner"] for d in ds.values())
        last = ds[max(ds)]
        text = (f"Day {day}: desk {((eq[-1]['value'] / eq[0]['value'] - 1) * 100 if len(eq) > 1 else 0):+.2f}%, "
                f"NIFTY {((mk[-1].close / mk[0].open - 1) * 100 if mk else 0):+.2f}%. Winners by bar: "
                + ", ".join(f"{a} {n}" for a, n in wins.items()) + ". Agent two-day records now: "
                + ", ".join(f"{a} {r}" for a, r in last["records"].items()) + ". Earlier lessons: " + " | ".join(lessons(bot)[-3:]))
        try:
            raw = prov.complete(desk.LESSON_SYSTEM, [{"role": "user", "content": text}])
            got = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
            ls = [str(x)[:160] for x in got.get("lessons", [])][:3]
            if ls:
                db.save_decision(f"desklesson:{bot['id']}", day, {"lessons": ls})
        except Exception as e:  # noqa: BLE001
            state["last_error"] = f"Lessons: {type(e).__name__}: {str(e)[:160]}"

    def finished(bot: dict, p: desk.Panel) -> bool:
        if bot["status"] != "running":
            return True
        if not bot["days"]:
            return False
        days = sorted({t[:10] for t in p.times if t > bot["start_time"]})
        return len(days) > bot["days"] or (len(days) == bot["days"] and p.times[-1].endswith("15:15"))

    def running() -> dict | None:
        return next((b for b in db.list_desks() if b["status"] == "running"), None)

    def desk_tick(now: datetime | None = None) -> None:
        now = now or datetime.now(market.IST)
        bot = running()
        if not bot or state["busy"]:
            return
        ist = now.astimezone(market.IST)
        hm = (ist.hour, ist.minute)
        if ist.weekday() >= 5 or not ((9, 45) <= hm <= (16, 15)):
            return
        state["busy"] = True
        try:
            p = panel() if db.get_market_bars(desk.MARKET, desk.INTERVAL) else None
            if p is None or stale(p, now):
                fetch("1d", 50)
                p = panel()
            step(bot, now)
            if finished(bot, p) and bot["days"]:
                db.set_desk_status(bot["id"], "finished")
            day = ist.date().isoformat()
            if hm >= (15, 50) and (bot["id"], day) not in state["lessons_done"]:
                state["lessons_done"].add((bot["id"], day))
                learn(bot, panel(), day)
        except Exception as e:  # noqa: BLE001 - the loop never dies; the error shows in the UI
            state["last_error"] = f"{type(e).__name__}: {str(e)[:200]}"
        finally:
            state["busy"] = False

    app.state.desk_tick = desk_tick

    # ----- view -----
    def view(bot: dict) -> dict:
        p = panel()
        book, start, ds = run_book(bot, p)
        cap = bot["capital"]
        m0 = p.market[start].close
        series = [{"time": e["time"], "value": e["value"], "market": round(cap * p.market[start + i].close / m0, 2)}
                  for i, e in enumerate(book["equity"])]
        last = series[-1]
        cost: dict[str, list[float]] = {}
        for tr in book["trades"]:
            q, c = cost.get(tr["symbol"], [0, 0.0])
            if tr["side"] == "BUY":
                cost[tr["symbol"]] = [q + tr["qty"], c + tr["qty"] * tr["price"]]
            elif q:
                cost[tr["symbol"]] = [q - tr["qty"], c * (q - tr["qty"]) / q]
        holdings = [{**h, "avg": round(cost[h["symbol"]][1] / cost[h["symbol"]][0], 2) if cost.get(h["symbol"], [0])[0] else None}
                    for h in book["holdings"]]
        names = {a["id"]: a["name"] for a in desk.AGENTS}
        wins = Counter(d["winner"] for d in ds.values())
        latest = ds[max(ds)] if ds else None
        agents = [{**a, "record_pct": latest["records"].get(a["id"]) if latest else None, "wins": wins.get(a["id"], 0),
                   "proposal": latest["proposals"].get(a["id"], {}) if latest else {}} for a in desk.AGENTS]
        ms = moods(bot)
        mood_t = max(ms) if ms else None
        is_done = finished(bot, p)
        days = sorted({t[:10] for t in p.times if t > bot["start_time"]})
        decisions = [{"time": t, "winner": d["winner"], "winner_name": names[d["winner"]], "reason": d.get("reason", ""),
                      "by": d.get("by"), "targets": {desk.short(s): w for s, w in d["targets"].items()},
                      "debate": [{**x, "name": names.get(x["agent"], x["agent"])} for x in d.get("debate", [])],
                      "confidence": d.get("confidence")} for t, d in sorted(ds.items(), reverse=True)[:40]]
        return {
            "bot": {**bot, "status": "finished" if is_done and bot["status"] == "running" else bot["status"]},
            "value": last["value"], "cash": book["cash"], "capital": cap,
            "return_pct": round((last["value"] / cap - 1) * 100, 2),
            "market_pct": round((last["market"] / cap - 1) * 100, 2), "edge": round(last["value"] - last["market"]),
            "day": len(days), "series": series, "trades": book["trades"][::-1][:300], "holdings": holdings,
            "decisions": decisions, "agents": agents,
            "mood": {"time": mood_t, "scores": {desk.short(s): v for s, v in ms[mood_t]["scores"].items()}} if mood_t else None,
            "lessons": lessons(bot)[-6:][::-1], "data_time": p.times[-1],
            "next_decision": None if is_done else next_bar_close(datetime.now(market.IST)).strftime("%H:%M"),
            "ai": bool(ai()), "last_error": state["last_error"], "market_name": desk.MARKET_NAME,
            "universe": [desk.short(s) for s in desk.UNIVERSE],
        }

    @app.get("/api/desk")
    def desk_get():
        bot = running() or next(iter(db.list_desks()), None)
        if not bot:
            return {"bot": None, "agents": desk.AGENTS, "universe": [desk.short(s) for s in desk.UNIVERSE]}
        p = panel() if db.get_market_bars(desk.MARKET, desk.INTERVAL) else None
        if bot["status"] == "running" and (p is None or stale(p, datetime.now(market.IST))):
            fetch("1d", 60)
        return view(bot)

    @app.post("/api/desk")
    def desk_start(body: StartIn):
        for b in db.list_desks():
            if b["status"] == "running":
                db.set_desk_status(b["id"], "stopped")
        fetch("1mo", 300)
        p = panel()
        days = f"{body.days} trading days" if body.days else "open-ended"
        bot = db.add_desk(f"Purple Desk · ₹{inr(body.capital)} · {days}", body.capital, body.days, p.times[-1])
        threading.Thread(target=lambda: _safe_step(bot), daemon=True).start()  # first decision without blocking
        return view(bot)

    def _safe_step(bot: dict, force: bool = True):
        if state["busy"]:
            return
        state["busy"] = True
        try:
            step(db.get_desk(bot["id"]), datetime.now(market.IST), force)
        except Exception as e:  # noqa: BLE001
            state["last_error"] = f"{type(e).__name__}: {str(e)[:200]}"
        finally:
            state["busy"] = False

    @app.post("/api/desk/stop")
    def desk_stop():
        bot = running()
        if not bot:
            raise HTTPException(404, "No bot is running.")
        db.set_desk_status(bot["id"], "stopped")
        return view(db.get_desk(bot["id"]))

    @app.post("/api/desk/decide")
    def desk_decide():
        """Decide the newest completed bar now (normally the live loop does this every 30 minutes)."""
        bot = running()
        if not bot:
            raise HTTPException(404, "No bot is running.")
        fetch("1d", 60)
        _safe_step(bot)
        return view(db.get_desk(bot["id"]))

    @app.get("/api/desk/backtest")
    def desk_backtest(days: int = 40, capital: float = 500_000):
        """The desk replayed on past 30-minute bars without AI (each bar follows the agent with the best record)."""
        days = max(7, min(days, 55))
        key = (days, capital)
        hit = state["backtest"]
        if hit and hit[0] == key and time.time() - hit[1] < BACKTEST_TTL:
            return hit[2]
        fetch("60d", BACKTEST_TTL)
        p = panel()
        start = max(5 * desk.BARS_PER_DAY, len(p) - days * desk.BARS_PER_DAY)
        bt = desk.backtest(p, capital, start)
        m0 = p.market[start].close
        eq = bt["sim"]["equity"]
        series = [{"time": e["time"], "value": e["value"], "market": round(capital * p.market[start + i].close / m0, 2)}
                  for i, e in enumerate(eq)][::3]
        weeks = desk.weekly(p, bt["sim"], start, capital)
        names = {a["id"]: a["name"] for a in desk.AGENTS}
        res = {"from": p.times[start], "to": p.times[-1], "capital": capital, "return_pct": bt["return_pct"],
               "market_pct": bt["market_pct"], "edge": round(eq[-1]["value"] - capital * (1 + bt["market_pct"] / 100)),
               "trades": len(bt["sim"]["trades"]), "series": series, "weeks": weeks,
               "weeks_beat": sum(w["beat"] for w in weeks),
               "agents": [{"id": a, "name": names[a], "return_pct": v["return_pct"],
                           "picked": sum(1 for w in bt["winners"].values() if w == a)} for a, v in bt["agents"].items()],
               "note": "Replayed without AI: each 30 minutes the desk follows the agent with the best two-day record. "
                       "The News & social agent has no past headlines here, so in this replay it means staying in cash."}
        state["backtest"] = (key, time.time(), res)
        return res
