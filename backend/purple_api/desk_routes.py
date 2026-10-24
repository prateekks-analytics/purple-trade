"""HTTP routes and the live loop of the portfolio bot (see desk.py). One bot runs at a time."""
from __future__ import annotations

import json
import threading
import time
from collections import Counter
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import coach, costs, desk, leaders, market, news
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
             "backtest": None, "guard_pause": 0.0, "daily_day": None, "daily_busy": False, "have30m": set()}
    lock = threading.Lock()

    def ai():
        p = app.state.provider
        return p if getattr(p, "name", "") in ("gemini", "groq", "ollama") and p.status()["available"] else None

    # ----- data -----
    def fetch(range_: str, max_age: float) -> None:
        """Download 30-minute bars for the basket and NIFTY 50 at most every `max_age` seconds per range."""
        with lock:
            if time.time() - state["fetched"].get(range_, 0) < max_age:
                return
            state["fetched"][range_] = time.time()
            _download(range_)

    def _download(range_: str) -> None:
        for s in symbols():
            # a stock the core just picked gets a month of history first, so its chart and costs are right
            rng = range_ if s in state["have30m"] or s in SYMBOLS else "1mo"
            try:
                db.upsert_bars(s, desk.INTERVAL, market.intraday_bars(s, desk.INTERVAL, rng))
                state["have30m"].add(s)
            except market.MarketError as e:
                state["last_error"] = f"{desk.short(s)}: {e}"
                if isinstance(e, market.RateLimited):
                    break

    def core_history(bot: dict | None = None) -> dict[str, dict]:
        bot = bot or running() or next(iter(db.list_desks()), None)
        return db.get_decisions(f"deskcore:{bot['id']}") if bot else {}

    def symbols() -> list[str]:
        """The 10 base stocks, NIFTY, and every stock the core has picked for this bot."""
        bot = running() or next(iter(db.list_desks()), None)
        risky = db.get_decisions(f"deskrisky:{bot['id']}") if bot else {}
        extra = sorted({s for h in (core_history(), risky) for c in h.values() for s in c.get("picks", [])} - set(SYMBOLS))
        return SYMBOLS + extra

    def panel() -> desk.Panel:
        mkt = db.get_market_bars(desk.MARKET, desk.INTERVAL)
        if len(mkt) < 60:
            raise HTTPException(503, "Not enough 30-minute prices yet. Check the internet connection and try again.")
        return coach.load_panel(db, [s for s in symbols() if s != desk.MARKET])

    def base(p: desk.Panel) -> desk.Panel:
        return coach.base_panel(p)

    # ----- the core: momentum leaders while NIFTY is in an uptrend (see leaders.py) -----
    def refresh_daily() -> None:
        """Once a day: two years of daily prices for the wide list and NIFTY (about 97 small downloads)."""
        try:
            for s in leaders.WIDE + [desk.MARKET]:
                try:
                    db.upsert_bars(s, "1d", market.daily_bars(s, "2y"))
                except market.RateLimited:
                    time.sleep(30)
                except market.MarketError:
                    continue
                time.sleep(0.3)
            today = datetime.now(market.IST).date().isoformat()
            fund = db.get_decisions("deskfund")
            if not fund or max(fund) < (datetime.now(market.IST) - timedelta(days=7)).date().isoformat():
                got = {}
                for s in desk.UNIVERSE:
                    try:
                        got[s] = market.fundamentals(s)
                    except market.MarketError:
                        continue
                    time.sleep(0.3)
                if got:
                    db.save_decision("deskfund", today, got)
            state["daily_day"] = today
        finally:
            state["daily_busy"] = False

    def core_for(bot: dict, day: str) -> dict:
        """The core's state for `day`, computed once and stored (so every decision that day agrees)."""
        hist = db.get_decisions(f"deskcore:{bot['id']}")
        if day in hist:
            return hist[day]
        mk = db.get_market_bars(desk.MARKET, "1d")
        if not mk or mk[-1].date[:10] < (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d"):
            return {"on": False, "picks": [], "refreshed": None, "gap_pct": None, "stale": True}
        prev = hist[max(hist)] if hist else None
        daily = {s: db.get_market_bars(s, "1d") for s in leaders.WIDE}
        got = leaders.today(prev, {s: r for s, r in daily.items() if r}, mk, day)
        db.save_decision(f"deskcore:{bot['id']}", day, got)
        return got

    def stale(p: desk.Panel, now: datetime) -> bool:
        """True when a newer bar than the newest stored one has completed."""
        return next_bar_close(_ist(p.times[-1]) + timedelta(minutes=30)) <= now.astimezone(market.IST)

    # ----- the bot's memory -----
    def moods(bot: dict) -> dict[str, dict]:
        return db.get_decisions(f"deskmood:{bot['id']}")

    def lessons(bot: dict) -> list[str]:
        return [x for d in db.get_decisions(f"desklesson:{bot['id']}").values() for x in d.get("lessons", [])]

    def read_mood(bot: dict, p: desk.Panel, now: datetime) -> None:
        """Headlines and trader posts for every stock, scored by one AI call. Kept per bar time."""
        prov = ai()
        if not prov:
            return
        blocks = []
        for s in desk.UNIVERSE:
            heads = [i["title"] for i in news.headlines(COMPANY[s], s, ["google"], limit=5)["items"]][:5]
            posts = [i["title"] for i in news.headlines(COMPANY[s], s, ["reddit"], limit=5)["items"]][:5]
            blocks.append(f"{desk.short(s)} ({COMPANY[s]}): News: " + (" | ".join(heads) or "none")
                          + " || Posts: " + (" | ".join(posts) or "none"))
        raw = prov.complete(desk.MOOD_SYSTEM, [{"role": "user", "content": "<data>\n" + "\n".join(blocks) + "\n</data>"}])
        scores = desk.parse_mood(raw)
        if scores:
            db.save_decision(f"deskmood:{bot['id']}", p.times[-1], {"scores": scores, "at": now.isoformat(timespec="minutes")})
        state["mood_at"][bot["id"]] = time.time()

    # ----- one decision -----
    def run_book(bot: dict, p: desk.Panel) -> tuple[dict, int, dict]:
        return coach.run_book(db, bot, p)

    def risky_for(bot: dict, day: str) -> list[str]:
        hist = db.get_decisions(f"deskrisky:{bot['id']}")
        if day in hist:
            return hist[day]["picks"]
        mk = db.get_market_bars(desk.MARKET, "1d")
        if not mk or mk[-1].date[:10] < (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d"):
            return []
        picks = leaders.risky({s: r for s in leaders.WIDE if (r := db.get_market_bars(s, "1d"))}, day)
        db.save_decision(f"deskrisky:{bot['id']}", day, {"picks": picks})
        return picks

    def decide(bot: dict, p: desk.Panel, t: int) -> dict:
        full = p
        if risky_for(bot, p.times[t][:10]) and not all(s in p.bars for s in risky_for(bot, p.times[t][:10])):
            fetch("1d", 0)  # a new high-beta pick: get its prices first
            full = p = panel()
        s0 = max(0, t - desk.RECORD_BARS - 3 * desk.BARS_PER_DAY)
        sh = desk.shadows(p, bot["capital"], coach.mood_index(p, moods(bot)), start=s0, ctx=coach.context(db, bot, p))
        props = {a: sh["agents"][a]["proposals"][t] for a in desk.AGENT_IDS}
        recs = {a: desk.record(sh["agents"][a]["sim"], s0, t) for a in desk.AGENT_IDS}
        book, _, ds = run_book(bot, p)
        prev = ds[max(ds)]["winner"] if ds else None
        ms = moods(bot)
        mood = ms[max(ms)]["scores"] if ms else None
        out = {"time": p.times[t], "records": {a: None if r is None else round(r * 100, 2) for a, r in recs.items()},
               "proposals": {a: {desk.short(s): w for s, w in v.items()} for a, v in props.items()}}
        core = core_for(bot, p.times[t][:10])
        if core["on"] and core["picks"] and all(s in full.bars for s in core["picks"]):
            names = ", ".join(desk.short(s) for s in core["picks"])
            return {**out, "winner": "core", "targets": {s: leaders.WEIGHT for s in core["picks"]}, "debate": [],
                    "confidence": None, "by": "rule:core",
                    "reason": f"NIFTY 50 is above its 200-day average, so the core strategy holds the 5 strongest stocks "
                              f"of the last 3 months out of {len(leaders.WIDE)} large and mid caps: {names}. "
                              "It refreshes them every 21 trading days."}
        prov = ai()
        if prov:
            rules = coach.live_rules()
            ids = [r["id"] for r in rules]
            raw = ""
            try:
                prompt = desk.chief_prompt(p.times[t], props, recs, book["holdings"], book["equity"][-1]["value"],
                                           sh["market"], t, mood, lessons(bot), rules,
                                           coach.latest_report(bot["id"], p.times[t]), costs.switch_cost_pct())
                raw = prov.complete(desk.CHIEF_SYSTEM, [{"role": "user", "content": prompt}])
                got = desk.parse_chief(raw, props, ids, allowed=list(full.bars))
                return {**out, **got, "rules_shown": ids, "by": f"{prov.name}:{prov.model}"}
            except Exception as e:  # noqa: BLE001 - any AI failure falls back to the track record
                state["last_error"] = f"AI chief: {type(e).__name__}: {str(e)[:160]}" + (f" | answer: {raw[:160]}" if raw else "")
        # no AI: follow the proven original five by record (a 13-analyst record-chase lost 6.9% vs -0.7% in replay)
        win = desk.judge({"agents": {a: sh["agents"][a] for a in desk.OLD_IDS}}, s0, t, prev if prev in desk.OLD_IDS else None)
        name = next(a["name"] for a in desk.AGENTS if a["id"] == win)
        return {**out, "winner": win, "targets": props[win], "debate": [], "confidence": None, "by": "record",
                "reason": (f"The AI's answer could not be used ({(state['last_error'] or '')[:60]}), so" if prov else "No AI answered, so")
                          + f" the desk followed {name}, the agent with the best two-day record."}

    def step(bot: dict, now: datetime, force: bool = False) -> bool:
        """Decide the newest completed bar if it has no decision yet. Older missed bars are skipped (held)."""
        p = panel()
        t = len(p) - 1
        if p.times[t] < bot["start_time"]:
            return False
        key = f"desk:{bot['id']}"
        if p.times[t] in db.get_decisions(key) or finished(bot, p):
            return False
        sold = guard_cash(bot, p.times[t])
        if sold:  # the crash guard holds cash for the rest of the day: no AI meeting, no mood read
            db.save_decision(key, p.times[t], {
                "time": p.times[t], "winner": "guard", "targets": {}, "debate": [], "confidence": None,
                "by": "rule:guard", "records": {}, "proposals": {},
                "reason": f"The crash guard sold everything at {sold['time']} after {desk.MARKET_NAME} fell fast. "
                          "The bot stays in cash for the rest of the day, so the AI manager does not meet."})
            return True
        if ai() and (force or time.time() - state["mood_at"].get(bot["id"], 0) > MOOD_EVERY):
            try:
                read_mood(bot, p, now)
            except Exception as e:  # noqa: BLE001
                state["last_error"] = f"News mood: {type(e).__name__}: {str(e)[:160]}"
                state["mood_at"][bot["id"]] = time.time()
        db.save_decision(key, p.times[t], after_guard(bot, p.times[t], decide(bot, p, t)))
        return True

    def guard_cash(bot: dict, bar: str) -> dict | None:
        """The market-drop guard sale of that day at or before this bar, if any."""
        return next((e for e in coach.guard_events(db, bot, bar[:10]) if e["bar"] <= bar and e["kind"] == "market"), None)

    def after_guard(bot: dict, bar: str, d: dict) -> dict:
        """Later the same day, a guard sale stands: no buying back what it sold (or anything, after a market drop)."""
        evs = [e for e in coach.guard_events(db, bot, bar[:10]) if e["bar"] <= bar]
        if not evs:
            return d
        if any(e["kind"] == "market" for e in evs):
            return {**d, "targets": {}, "reason": "Crash guard: in cash for the rest of the day. " + d.get("reason", "")}
        blocked = {s for e in evs for s in e["symbols"]}
        kept = {s: w for s, w in d["targets"].items() if s not in blocked}
        if kept == d["targets"]:
            return d
        return {**d, "targets": kept, "reason": d.get("reason", "") + " Crash guard: "
                + ", ".join(desk.short(s) for s in sorted(blocked)) + " not bought back today."}

    def guard_tick(bot: dict, now: datetime) -> None:
        """Every minute in the session: sell into a fast fall (see desk.guard_check). No AI calls."""
        if time.time() < state["guard_pause"]:
            return
        ist = now.astimezone(market.IST)
        day = ist.date().isoformat()
        evs = coach.guard_events(db, bot, day)
        if any(e["kind"] == "market" for e in evs):
            return
        p = panel()
        book, start, ds = run_book(bot, p)
        held = {f"{h['symbol']}.NS" for h in book["holdings"]}
        if p.times[-1] in ds:  # the decision on the last completed bar was filled at this bar's open
            held = set(ds[p.times[-1]]["targets"])
        held -= {s for e in evs for s in e["symbols"]}
        if not held:
            return
        try:
            m_now, m_win = market.recent_prices(desk.MARKET, desk.GUARD_WINDOW_MIN, now)
            s_now, s_high = {}, {}
            for s in held:
                price, win = market.recent_prices(s, desk.GUARD_WINDOW_MIN, now)
                bought = max((tr["time"] for tr in book["trades"] if tr["symbol"] == desk.short(s) and tr["side"] == "BUY"),
                             default=p.times[start])
                closes = [b.close for b, t in zip(p.bars.get(s, []), p.times) if t >= bought]
                s_now[s], s_high[s] = price, max(closes + win + [price])
        except market.RateLimited:
            state["guard_pause"] = time.time() + 600
            return
        hit = desk.guard_check(sorted(held), m_now, m_win, s_now, s_high)
        if hit:
            k = max(0, (ist.hour * 60 + ist.minute - (9 * 60 + 15)) // 30)
            bar = f"{day} {(9 * 60 + 15 + 30 * k) // 60:02d}:{(9 * 60 + 15 + 30 * k) % 60:02d}"
            db.save_decision(f"deskguard:{bot['id']}", ist.strftime("%Y-%m-%d %H:%M:%S"),
                             {"bar": bar, "day": day, "kind": hit["kind"], "symbols": hit["symbols"],
                              "prices": {s: s_now[s] for s in hit["symbols"]}, "reason": hit["reason"],
                              "time": ist.strftime("%H:%M")})

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
        in_session = ist.weekday() < 5 and (9, 16) <= hm <= (15, 30)
        if ist.weekday() < 5 and hm >= (8, 30) and state["daily_day"] != ist.date().isoformat() and not state["daily_busy"]:
            state["daily_busy"] = True
            threading.Thread(target=refresh_daily, name="purple-daily", daemon=True).start()
        if ist.weekday() >= 5 or not (in_session or (9, 45) <= hm <= (16, 15)):
            return
        state["busy"] = True
        try:
            if in_session and db.get_market_bars(desk.MARKET, desk.INTERVAL):
                try:
                    guard_tick(bot, now)
                except Exception as e:  # noqa: BLE001 - a guard failure never blocks the decisions
                    state["last_error"] = f"Crash guard: {type(e).__name__}: {str(e)[:160]}"
            if not (9, 45) <= hm <= (16, 15):
                return
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
        names = {a["id"]: a["name"] for a in desk.AGENTS + [desk.CORE]}
        wins = Counter(d["winner"] for d in ds.values())
        tw = coach.twin(db, bot, p)
        latest = ds[max(ds)] if ds else None
        agents = [{**a, "record_pct": latest["records"].get(a["id"]) if latest else None, "wins": wins.get(a["id"], 0),
                   "proposal": latest["proposals"].get(a["id"], {}) if latest else {}} for a in desk.AGENTS]
        ch = core_history(bot)
        core = ch[max(ch)] if ch else {"on": False, "picks": [], "gap_pct": None}
        agents.append({**desk.CORE, "record_pct": None, "wins": wins.get("core", 0),
                       "proposal": {desk.short(s): leaders.WEIGHT for s in core.get("picks", [])}})
        ms = moods(bot)
        mood_t = max(ms) if ms else None
        is_done = finished(bot, p)
        days = sorted({t[:10] for t in p.times if t > bot["start_time"]})
        decisions = [{"time": t, "winner": d["winner"], "winner_name": names[d["winner"]], "reason": d.get("reason", ""),
                      "by": d.get("by"), "targets": {desk.short(s): w for s, w in d["targets"].items()},
                      "debate": [{**x, "name": names.get(x["agent"], x["agent"])} for x in d.get("debate", [])],
                      "confidence": d.get("confidence"), "rules_used": d.get("rules_used", []),
                      "uses": [names.get(u, u) for u in d.get("uses", [])]}
                     for t, d in sorted(ds.items(), reverse=True)[:40]]
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
            "coach": coach_view(bot, p, book, start, ds),
            "twin": {"value": tw["value"], "return_pct": tw["return_pct"], "edge": round(last["value"] - tw["value"])}
            if tw else None,
            "core": {"on": bool(core.get("on")), "picks": [desk.short(x) for x in core.get("picks", [])],
                     "gap_pct": core.get("gap_pct"), "refreshed": core.get("refreshed"), "pool": len(leaders.WIDE)},
            "guard": [{"time": e["time"], "kind": e["kind"], "reason": e["reason"]}
                      for e in coach.guard_events(db, bot, datetime.now(market.IST).date().isoformat())],
        }

    def coach_view(bot: dict | None, p=None, book=None, start=0, ds=None) -> dict:
        rules = coach.live_rules()
        score = coach.scorecard(p, book, start, ds, rules) if bot and p is not None else {}
        return {"rules": [{**r, "score": score.get(r["id"])} for r in rules]}

    @app.get("/api/desk")
    def desk_get():
        bot = running() or next(iter(db.list_desks()), None)
        if not bot:
            return {"bot": None, "agents": desk.AGENTS, "universe": [desk.short(s) for s in desk.UNIVERSE],
                    "coach": coach_view(None)}
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

    @app.get("/api/desk/review")
    def desk_review(day: str | None = None, save: bool = False):
        """Review pack for one trading day (default: the newest day with decisions) of the running or newest bot.
        save=true also writes coach/reviews/<day>.md and .json for the /coach-bot review."""
        if day is not None and not (len(day) == 10 and day[4] == day[7] == "-" and day.replace("-", "").isdigit()):
            raise HTTPException(422, "day must be YYYY-MM-DD")
        bot = coach.pick_bot(db)
        if not bot:
            raise HTTPException(404, "No bot has run yet.")
        pack = coach.build_review(db, bot, day, panel())
        if save:
            pack["saved_to"] = str(coach.write_review(pack))
        return pack

    @app.get("/api/desk/lab")
    def desk_lab():
        """Strategy lab: paper-only candidates, their backtest evidence and the board's next step (see lab.py)."""
        return coach.lab_report(db, panel())

    @app.get("/api/desk/journal")
    def desk_journal():
        """The coach's daily reports (coach/reports.json, newest first) and its journal (coach/journal.md) for days
        without a report; both are pulled from the state dataset online."""
        return {"reports": coach.read_reports()[::-1], "entries": coach.read_journal()}

    @app.post("/api/desk/coach/rules/{rule_id}/retire")
    def coach_retire(rule_id: str):
        """Remove a coach rule from what the chief reads (kept in the playbook as retired)."""
        try:
            coach.retire(rule_id)
        except KeyError:
            raise HTTPException(404, "No live coach rule with that id.") from None
        return coach_view(None)

    @app.get("/api/desk/backtest")
    def desk_backtest(days: int = 40, capital: float = 500_000):
        """The desk replayed on past 30-minute bars without AI (each bar follows the agent with the best record)."""
        days = max(7, min(days, 55))
        key = (days, capital)
        hit = state["backtest"]
        if hit and hit[0] == key and time.time() - hit[1] < BACKTEST_TTL:
            return hit[2]
        fetch("60d", BACKTEST_TTL)
        p = base(panel())
        start = max(5 * desk.BARS_PER_DAY, len(p) - days * desk.BARS_PER_DAY)
        bt = desk.backtest(p, capital, start, agents=desk.OLD_IDS)  # what the bot does when no AI answers
        m0 = p.market[start].close
        eq = bt["sim"]["equity"]
        series = [{"time": e["time"], "value": e["value"], "market": round(capital * p.market[start + i].close / m0, 2)}
                  for i, e in enumerate(eq)][::3]
        weeks = desk.weekly(p, bt["sim"], start, capital)
        names = {a["id"]: a["name"] for a in desk.AGENTS + [desk.CORE]}
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
