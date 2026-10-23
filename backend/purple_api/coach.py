"""Claude coaches the bot: a daily review pack, a short playbook the AI chief reads, and a scorecard per rule.

Claude never runs inside the live loop. After a trading day a Claude Code session (the /coach-bot command) reads the
review pack, judges each decision on what the desk knew at the time, and edits `purple/coach/playbook.md`. The chief
(Gemini, every 30 minutes) reads the active rules as guidance inside <data> tags; the hard caps in desk.parse_chief
stay authoritative. Each chief decision lists the rule ids it followed (`rules_used`), so the scorecard can compare
decisions that followed a rule with decisions that saw it and did not.

CLI (no server needed, reads the same database):
    python -m purple_api.coach review [--day YYYY-MM-DD]   writes coach/reviews/<day>.md and .json
    python -m purple_api.coach report --notes notes.json   adds the day's report (notes + numbers) to reports.json
    python -m purple_api.coach check                        validates playbook.md and lists the active rules
    python -m purple_api.coach compare [--days 40 20 10]    one winner vs team mixes, replayed without AI
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from . import costs, desk

HORIZONS = (1, 3, desk.BARS_PER_DAY)  # bars after the decision: 30 minutes, 1.5 hours, one trading day
MAX_ACTIVE = 10
LIVE = ("active", "trial")  # statuses the chief reads; trial = one day of evidence so far
PLAYBOOK_HEAD = """# Purple Desk coach playbook

Rules the AI chief reads before every 30-minute decision, written by Claude after each trading day (/coach-bot).
At most 10 live rules (status active or trial). Hard limits in code (35% per stock, long only) always win.
Format per rule: a `## <id> | <active|trial|retired> | added <YYYY-MM-DD>` line (retired rules add
`| retired <YYYY-MM-DD>`), then `Rule:` and `Why:` lines.
"""


def coach_dir() -> Path:
    return Path(os.environ.get("PURPLE_COACH_DIR") or Path(__file__).resolve().parents[2] / "coach")


# ---------- the playbook ----------

_HEAD = re.compile(r"^##\s+(R\d+)\s*\|\s*(active|trial|retired)\s*\|\s*added\s+(\d{4}-\d{2}-\d{2})"
                   r"(?:\s*\|\s*retired\s+(\d{4}-\d{2}-\d{2}))?\s*$", re.I)


def parse_playbook(text: str) -> list[dict]:
    rules, cur = [], None
    for line in text.splitlines():
        m = _HEAD.match(line.strip())
        if m:
            cur = {"id": m[1].upper(), "status": m[2].lower(), "added": m[3], "retired": m[4], "text": "", "why": ""}
            rules.append(cur)
        elif cur and line.strip().lower().startswith("rule:"):
            cur["text"] = line.split(":", 1)[1].strip()
        elif cur and line.strip().lower().startswith("why:"):
            cur["why"] = line.split(":", 1)[1].strip()
        elif line.startswith("#"):
            cur = None
    return [r for r in rules if r["text"]]


def render_playbook(rules: list[dict]) -> str:
    out = [PLAYBOOK_HEAD]
    for r in rules:
        head = f"## {r['id']} | {r['status']} | added {r['added']}" + (f" | retired {r['retired']}" if r.get("retired") else "")
        out += [head, f"Rule: {r['text']}", f"Why: {r['why']}", ""]
    return "\n".join(out)


def read_playbook() -> list[dict]:
    try:
        return parse_playbook((coach_dir() / "playbook.md").read_text(encoding="utf-8"))
    except OSError:
        return []


def live_rules(rules: list[dict] | None = None) -> list[dict]:
    rules = read_playbook() if rules is None else rules
    return [r for r in rules if r["status"] in LIVE][:MAX_ACTIVE]


def retire(rule_id: str, today: str | None = None) -> dict:
    rules = read_playbook()
    hit = next((r for r in rules if r["id"] == rule_id.upper() and r["status"] in LIVE), None)
    if not hit:
        raise KeyError(rule_id)
    hit["status"], hit["retired"] = "retired", today or date.today().isoformat()
    path = coach_dir() / "playbook.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_playbook(rules), encoding="utf-8")
    return hit


# ---------- the journal (one entry per review, shown in the app's Daily review tab) ----------

_ENTRY = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*·\s*review of\s+(\d{4}-\d{2}-\d{2})", re.I)
_ITEM = re.compile(r"^-\s+([^:]{1,40}):\s*(.*)$")


def parse_journal(text: str) -> list[dict]:
    """Journal entries newest first: {date, day, summary, items: [{label, text}]}. Lines that are not a new
    `- Label: text` bullet continue the previous one."""
    entries, cur = [], None
    for line in text.splitlines():
        s = line.strip()
        m = _ENTRY.match(s)
        if m:
            cur = {"date": m[1], "day": m[2], "summary": None, "items": []}
            entries.append(cur)
        elif s.startswith("#"):
            cur = None
        elif cur is not None and s:
            it = _ITEM.match(s)
            if it:
                cur["items"].append({"label": it[1].strip(), "text": it[2].strip()})
            elif cur["items"]:
                cur["items"][-1]["text"] += " " + s.lstrip("- ")
    for e in entries:
        summ = next((i for i in e["items"] if i["label"].lower() == "summary"), None)
        if summ:
            e["summary"] = summ["text"]
            e["items"].remove(summ)
    return sorted(entries, key=lambda e: (e["day"], e["date"]), reverse=True)


def read_journal() -> list[dict]:
    try:
        return parse_journal((coach_dir() / "journal.md").read_text(encoding="utf-8"))
    except OSError:
        return []


# ---------- the daily report (the coach's verdict + facts from code; shown in Daily review, read by the manager) ----------

GRADES, TRUST, WHO = ("strong", "average", "weak"), ("more", "same", "less"), ("coach", "owner")


def _txt(x, n: int) -> str:
    return " ".join(str(x or "").split())[:n]


def make_report(pack: dict, notes: dict) -> dict:
    """Join the coach's notes (plain words, grades, ideas) with the numbers the code computed, so the report never
    restates a number by hand. Raises ValueError on notes the app cannot show."""
    if not pack.get("summary"):
        raise ValueError("no decisions on that day")
    ids = {r["id"] for r in pack.get("report_card", [])}
    grades = notes.get("grades") or {}
    if not isinstance(grades, dict) or not grades:
        raise ValueError("grades: give every analyst a grade")
    cards = []
    for r in pack["report_card"]:
        g = grades.get(r["id"]) or {}
        if r["id"] != "twin" and (g.get("grade") not in GRADES or g.get("trust") not in TRUST):
            raise ValueError(f"grades.{r['id']}: grade must be one of {GRADES} and trust one of {TRUST}")
        cards.append({**r, "grade": g.get("grade"), "trust": g.get("trust"), "why": _txt(g.get("why"), 220)})
    unknown = set(grades) - ids
    if unknown:
        raise ValueError(f"grades: unknown analyst ids {sorted(unknown)}")
    ideas = [{"title": _txt(i.get("title"), 90), "detail": _txt(i.get("detail"), 400),
              "who": i.get("who") if i.get("who") in WHO else "owner", "expected": _txt(i.get("expected"), 160)}
             for i in (notes.get("ideas") or []) if isinstance(i, dict) and i.get("title")][:4]
    advice = [{"rule": _txt(a.get("rule"), 8), "followed": _txt(a.get("followed"), 160),
               "helped": a.get("helped") if a.get("helped") in ("yes", "no", "too early") else "too early",
               "note": _txt(a.get("note"), 240)} for a in (notes.get("advice_check") or []) if isinstance(a, dict)]
    if not _txt(notes.get("headline"), 10) or not _txt(notes.get("story"), 10):
        raise ValueError("headline and story are required")
    sm, cs = pack["summary"], pack.get("costs") or {}
    return {"day": pack["day"], "bot_id": pack["bot"]["id"], "capital": pack["bot"]["capital"],
            "headline": _txt(notes["headline"], 220), "story": _txt(notes["story"], 1400),
            "numbers": {k: sm.get(k) for k in ("desk_pct", "nifty_pct", "twin_pct", "company_rupees",
                                               "company_since_start_pct", "nifty_since_start_pct", "trades",
                                               "decisions", "by_ai", "day_complete")},
            "costs": {"day": cs.get("day"), "since_start": cs.get("since_start"), "switch_pct": costs.switch_cost_pct(),
                      "note": _txt(notes.get("costs_note"), 400)},
            "cards": cards, "advice_check": advice,
            "rule_changes": [_txt(x, 300) for x in (notes.get("rule_changes") or []) if _txt(x, 1)][:6],
            "ideas": ideas, "watch": _txt(notes.get("watch"), 300)}


def read_reports() -> list[dict]:
    try:
        data = json.loads((coach_dir() / "reports.json").read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_report(rep: dict) -> Path:
    """reports.json keeps one report per bot and day, oldest first."""
    reps = [r for r in read_reports() if (r.get("bot_id"), r.get("day")) != (rep["bot_id"], rep["day"])] + [rep]
    reps.sort(key=lambda r: (r.get("day") or "", r.get("bot_id") or ""))
    path = coach_dir() / "reports.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reps, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def latest_report(bot_id: str, before: str | None = None) -> dict | None:
    """The newest report of this bot for a day before `before` (a bar time), so a decision only sees past reviews."""
    reps = [r for r in read_reports() if r.get("bot_id") == bot_id and (before is None or r.get("day", "") < before[:10])]
    return reps[-1] if reps else None


def check(rules: list[dict], text: str) -> list[str]:
    """Problems with a playbook: unparsed rule headings, duplicate ids, too many live rules, missing why."""
    errs = []
    heads = [ln for ln in text.splitlines() if ln.startswith("## ")]
    if len(heads) != len(rules):
        errs.append(f"{len(heads)} '## ' headings but {len(rules)} rules parsed: check the heading format and Rule: lines")
    ids = Counter(r["id"] for r in rules)
    errs += [f"duplicate id {i}" for i, n in ids.items() if n > 1]
    live = [r for r in rules if r["status"] in LIVE]
    if len(live) > MAX_ACTIVE:
        errs.append(f"{len(live)} live rules; at most {MAX_ACTIVE}")
    errs += [f"{r['id']} has no Why:" for r in live if not r["why"]]
    return errs


# ---------- shared desk helpers (used by desk_routes too) ----------

def load_panel(db, syms: list[str] | None = None) -> desk.Panel:
    """30-minute panel; by default the base stocks plus every stock the core picked (all 30-minute data stored)."""
    if syms is None:
        have = {r for r in db.market_symbols(desk.INTERVAL)} if hasattr(db, "market_symbols") else set()
        syms = desk.UNIVERSE + sorted(have - set(desk.UNIVERSE) - {desk.MARKET})
    return desk.align({s: db.get_market_bars(s, desk.INTERVAL) for s in syms},
                      db.get_market_bars(desk.MARKET, desk.INTERVAL))


def base_panel(p: desk.Panel) -> desk.Panel:
    """Only the 10 base stocks: the five agents never trade the core's picks."""
    return desk.Panel(p.times, {s: b for s, b in p.bars.items() if s in desk.UNIVERSE}, p.market)


def run_book(db, bot: dict, p: desk.Panel) -> tuple[dict, int, dict]:
    """The bot's own portfolio replayed from its stored decisions. Returns (sim, start index, decisions)."""
    start = p.times.index(bot["start_time"]) if bot["start_time"] in p.times else \
        next((i for i, t in enumerate(p.times) if t >= bot["start_time"]), len(p) - 1)
    ds = db.get_decisions(f"desk:{bot['id']}")
    idx = {t: i for i, t in enumerate(p.times)}
    targets = {idx[t]: d["targets"] for t, d in ds.items() if t in idx}
    notes = {idx[t]: d["winner"] for t, d in ds.items() if t in idx}
    exits: dict[int, list] = {}
    for ev in db.get_decisions(f"deskguard:{bot['id']}").values():
        i = idx.get(ev["bar"], len(p) if p.times and ev["bar"] > p.times[-1] else None)
        if i is not None:
            exits.setdefault(i, []).extend((s, px, "crash guard") for s, px in ev["prices"].items())
    return desk.simulate(p, targets, bot["capital"], start, notes, exits, steady_from=desk.STEADY_FROM), start, ds


def guard_events(db, bot: dict, day: str | None = None) -> list[dict]:
    evs = db.get_decisions(f"deskguard:{bot['id']}")
    return [{**e, "at": k} for k, e in sorted(evs.items()) if day is None or e["day"] == day]


def mood_index(p: desk.Panel, ms: dict[str, dict], key: str = "score") -> dict[int, dict[str, float]]:
    """Mood reads by panel bar. key "score" = news mood, "social" = trader-post mood (older reads: news only)."""
    out = {}
    for ts, m in ms.items():
        i = max((i for i, t in enumerate(p.times) if t <= ts), default=None)
        if i is not None:
            out[i] = {s: v.get(key, v["score"]) for s, v in m["scores"].items()}
    return out


def context(db, bot: dict | None, p: desk.Panel) -> dict:
    """What the analysts need besides 30-minute prices: daily trends, company figures, social mood, risky picks."""
    daily = {s: db.get_market_bars(s, "1d") for s in desk.UNIVERSE + [desk.MARKET]}
    ctx = {"daily": desk.daily_context(p, {s: r for s, r in daily.items() if r})}
    fund = db.get_decisions("deskfund")
    if fund and len(p):
        ctx["fund"] = desk.fundamental_scores(fund[max(fund)], p.times[-1])
    if bot:
        ctx["social"] = mood_index(p, db.get_decisions(f"deskmood:{bot['id']}"), "social")
        risky = db.get_decisions(f"deskrisky:{bot['id']}")
        ctx["risky"] = {i: risky[t[:10]]["picks"] for i, t in enumerate(p.times) if t[:10] in risky}
    return ctx


_TWIN: dict = {}


def twin(db, bot: dict, p: desk.Panel) -> dict | None:
    """The original desk (5 agents, best two-day record, no AI) run silently on the same money since the bot's
    start, to measure whether the analyst company does better."""
    key = (bot["id"], p.times[-1] if len(p) else None, len(p))
    if key in _TWIN:
        return _TWIN[key]
    start = p.times.index(bot["start_time"]) if bot["start_time"] in p.times else \
        next((i for i, t in enumerate(p.times) if t >= bot["start_time"]), None)
    if start is None:
        return None
    b = base_panel(p)
    s0 = max(0, start - desk.RECORD_BARS - 1)
    sh = desk.shadows(b, bot["capital"], mood_index(b, db.get_decisions(f"deskmood:{bot['id']}")), start=s0,
                      agents=desk.OLD_IDS)
    targets, cur = {}, None
    for t in range(start, len(b)):
        cur = desk.judge(sh, s0, t, cur)
        targets[t] = sh["agents"][cur]["proposals"][t]
    sim = desk.simulate(b, targets, bot["capital"], start)
    out = {"equity": sim["equity"], "value": sim["equity"][-1]["value"], "trades": sim["trades"],
           "return_pct": round((sim["equity"][-1]["value"] / bot["capital"] - 1) * 100, 2)}
    _TWIN.clear()
    _TWIN[key] = out
    return out


# ---------- outcomes and the scorecard ----------

def _ret(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None or not a else round((b / a - 1) * 100, 3)


def outcomes(p: desk.Panel, book: dict, start: int, t: int, sh: dict | None = None, s0: int = 0) -> dict:
    """Returns (%) from bar t's close over the next 1, 3 and 13 bars: desk, NIFTY and each agent's shadow portfolio.
    None where those bars have not happened yet."""
    eq = book["equity"]

    def at(seq, i):
        return seq[i] if 0 <= i < len(seq) else None
    out = {}
    for h in HORIZONS:
        e0, e1 = at(eq, t - start), at(eq, t - start + h)
        m0, m1 = at(p.market, t), at(p.market, t + h)
        row = {"desk": _ret(e0 and e0["value"], e1 and e1["value"]), "nifty": _ret(m0 and m0.close, m1 and m1.close)}
        if sh:
            for a in desk.AGENT_IDS:
                se = sh["agents"][a]["sim"]["equity"]
                a0, a1 = at(se, t - s0), at(se, t - s0 + h)
                row[a] = _ret(a0 and a0["value"], a1 and a1["value"])
        out[str(h)] = row
    return out


def _by_ai(d: dict) -> bool:
    """Decided by the AI manager (not the track record, the core rule or the crash guard holding cash)."""
    by = d.get("by") or ""
    return by != "record" and not by.startswith("rule:")


def scorecard(p: desk.Panel, book: dict, start: int, ds: dict, rules: list[dict]) -> dict[str, dict]:
    """Per rule: 3-bar edge vs NIFTY (desk minus NIFTY, %) of AI decisions that cited it vs those that saw it and
    did not. Decisions decided by the track record are left out (the judge does not read rules)."""
    idx = {t: i for i, t in enumerate(p.times)}
    edges = {}
    for ts, d in ds.items():
        if ts in idx and _by_ai(d):
            o = outcomes(p, book, start, idx[ts])["3"]
            if o["desk"] is not None and o["nifty"] is not None:
                edges[ts] = o["desk"] - o["nifty"]

    def stats(times):
        xs = [edges[t] for t in times]
        return {"n": len(xs), "days": len({t[:10] for t in times}),
                "edge_pct": round(sum(xs) / len(xs), 3) if xs else None}
    out = {}
    for r in rules:
        seen = [t for t in edges if r["id"] in (ds[t].get("rules_shown") or [])]
        cited = [t for t in seen if r["id"] in (ds[t].get("rules_used") or [])]
        a, b = stats(cited), stats([t for t in seen if t not in cited])
        if a["n"] < 4 or a["days"] < 2:
            verdict = "too early"
        else:
            diff = a["edge_pct"] - (b["edge_pct"] if b["n"] else 0.0)
            verdict = "helping" if diff > 0.05 else "hurting" if diff < -0.05 else "no clear effect"
        out[r["id"]] = {"followed": a, "not_followed": b, "verdict": verdict}
    return out


# ---------- the review pack ----------

def latest_day(ds: dict) -> str | None:
    return max(ds)[:10] if ds else None


def build_review(db, bot: dict, day: str | None = None, p: desk.Panel | None = None) -> dict:
    """Everything a reviewer needs for one trading day: what the desk knew at each decision, then the outcomes."""
    p = p or load_panel(db)
    book, start, ds = run_book(db, bot, p)
    day = day or latest_day(ds)
    idx = {t: i for i, t in enumerate(p.times)}
    todays = sorted(t for t in ds if t.startswith(day or "~") and t in idx)
    names = {a["id"]: a["name"] for a in desk.AGENTS + [desk.CORE]}
    rules = read_playbook()
    pack = {"bot": {k: bot[k] for k in ("id", "name", "capital", "days", "start_time", "status")}, "day": day,
            "data_time": p.times[-1] if len(p) else None, "decisions": [],
            "playbook": rules, "scorecard": scorecard(p, book, start, ds, rules)}
    if not todays:
        pack["summary"] = None
        return pack
    i0, i1 = idx[todays[0]], idx[todays[-1]]
    last_bar = max(i for i, t in enumerate(p.times) if t.startswith(day))
    first_bar = min(i for i, t in enumerate(p.times) if t.startswith(day))
    s0 = min(start, max(0, i0 - desk.RECORD_BARS - 3 * desk.BARS_PER_DAY))  # from the bot's start: since-start cards
    ms = db.get_decisions(f"deskmood:{bot['id']}")
    sh = desk.shadows(p, bot["capital"], mood_index(p, ms), start=s0, ctx=context(db, bot, p))
    mkt = sh["market"]
    eq = book["equity"]
    base = first_bar - 1 if first_bar - 1 >= start else start
    d0, d1 = eq[base - start]["value"], eq[min(last_bar, len(p) - 1) - start]["value"]
    m0 = p.market[first_bar - 1].close if first_bar > 0 else p.market[first_bar].open
    m1 = p.market[last_bar].close
    trades = [tr for tr in book["trades"] if tr["time"].startswith(day)]
    wins = Counter(ds[t]["winner"] for t in todays)
    pack["summary"] = {
        "desk_pct": _ret(d0, d1), "nifty_pct": _ret(m0, m1), "decisions": len(todays),
        "by_ai": sum(1 for t in todays if _by_ai(ds[t])),
        "winners": {names[a]: n for a, n in wins.most_common()}, "trades": len(trades),
        "bought": sum(tr["value"] for tr in trades if tr["side"] == "BUY"),
        "sold": sum(tr["value"] for tr in trades if tr["side"] == "SELL"),
        "day_complete": p.times[last_bar][11:] >= "15:15",  # Yahoo sometimes adds a 15:30 stub bar
        "twin_pct": _twin_day(db, bot, p, start, base, last_bar),
        "company_rupees": round(d1 - d0), "company_since_start_pct": _ret(eq[0]["value"], d1),
        "nifty_since_start_pct": _ret(p.market[start].close, m1),
    }
    pack["costs"] = costs.summary(book["trades"], day)
    pack["report_card"] = report_card(db, bot, p, sh, s0, start, base, last_bar, day, [ds[t] for t in todays])
    for ts in todays:
        t, d = idx[ts], ds[ts]
        mood_t = max((k for k in ms if k <= ts), default=None)
        mood = ms[mood_t]["scores"] if mood_t else {}
        cases = {x.get("agent"): x.get("case", "") for x in d.get("debate", [])}
        knew = {
            "nifty": {"close": round(mkt.close[t], 1), "today_pct": round((mkt.ret_day[t] or 0) * 100, 2),
                      "above_50_bar_avg": bool(mkt.ema50[t] and mkt.close[t] > mkt.ema50[t])},
            "mood": {"read_at": mood_t, "scores": {desk.short(s): {"score": v["score"], "why": v.get("why", "")}
                                                  for s, v in mood.items()}} if mood_t else None,
            "agents": [{"id": a, "name": names[a], "proposal": d.get("proposals", {}).get(a, {}),
                        "record_2d_pct": (d.get("records") or {}).get(a), "case": cases.get(a, "")}
                       for a in desk.AGENT_IDS],
            "rules_shown": d.get("rules_shown", []),
        }
        chose = {"winner": d["winner"], "winner_name": names[d["winner"]],
                 "targets": {desk.short(s): w for s, w in d["targets"].items()}, "reason": d.get("reason", ""),
                 "confidence": d.get("confidence"), "by": d.get("by") or "", "rules_used": d.get("rules_used", [])}
        pack["decisions"].append({"time": ts, "knew": knew, "chose": chose,
                                  "outcome": outcomes(p, book, start, t, sh, s0)})
    return pack


def report_card(db, bot, p, sh, s0, start, base_i, last_bar, day, todays: list[dict]) -> list[dict]:
    """Every analyst's own paper portfolio (same money, same simple fees) today and since the bot's start, how often
    it led or was used today, and what its trading today would cost in real taxes and charges. Plus the old-bot twin."""
    names = {a["id"]: a for a in desk.AGENTS}
    rows = []
    for a in desk.AGENT_IDS:
        sim = sh["agents"][a]["sim"]
        eq = sim["equity"]

        def v(i):
            j = i - s0
            return eq[j]["value"] if 0 <= j < len(eq) else None
        led = costs.ledger(sim["trades"]).get(day) or {}
        rows.append({"id": a, "name": names[a]["name"], "team": names[a]["team"],
                     "today_pct": _ret(v(base_i), v(last_bar)), "since_start_pct": _ret(v(start), v(last_bar)),
                     "trades_today": sum(1 for t in sim["trades"] if t["time"].startswith(day)),
                     "costs_today": led.get("total", 0.0),
                     "led_today": sum(1 for d in todays if d.get("winner") == a),
                     "used_today": sum(1 for d in todays if a in (d.get("uses") or [d.get("winner")]))})
    tw = twin(db, bot, p)
    if tw:
        eq = tw["equity"]

        def tv(i):
            j = i - start
            return eq[j]["value"] if 0 <= j < len(eq) else None
        led = costs.ledger(tw["trades"]).get(day) or {}
        rows.append({"id": "twin", "name": "Old bot (original five, no AI)", "team": "For comparison",
                     "today_pct": _ret(tv(base_i), tv(last_bar)), "since_start_pct": _ret(tv(start), tv(last_bar)),
                     "trades_today": sum(1 for t in tw["trades"] if t["time"].startswith(day)),
                     "costs_today": led.get("total", 0.0), "led_today": 0, "used_today": 0})
    return rows


def _twin_day(db, bot, p, start, base_i, last_bar):
    tw = twin(db, bot, p)
    if not tw:
        return None
    eq = tw["equity"]
    i0, i1 = base_i - start, min(last_bar, len(p) - 1) - start
    return _ret(eq[i0]["value"], eq[i1]["value"]) if 0 <= i0 < len(eq) and 0 <= i1 < len(eq) else None


def _f(x, unit="%") -> str:
    return "—" if x is None else f"{x:+.2f}{unit}"


def review_markdown(pack: dict) -> str:
    s = pack.get("summary")
    L = [f"# Purple Desk review · {pack['day'] or 'no decisions yet'}", "",
         f"Bot: {pack['bot']['name']} (id {pack['bot']['id']}, started {pack['bot']['start_time']}, {pack['bot']['status']}). "
         f"Prices up to {pack['data_time']}.", ""]
    if not s:
        return "\n".join(L + ["No decisions on this day."])
    L += ["## Day summary", "",
          f"- Company {_f(s['desk_pct'])} vs NIFTY 50 {_f(s['nifty_pct'])} vs old-bot twin {_f(s.get('twin_pct'))} "
          f"(previous close to last bar{'' if s['day_complete'] else ', day not finished'}).",
          f"- {s['decisions']} decisions ({s['by_ai']} by AI). Winners: "
          + ", ".join(f"{a} {n}" for a, n in s["winners"].items()) + ".",
          f"- {s['trades']} trades: bought Rs {s['bought']:,.0f}, sold Rs {s['sold']:,.0f}.", ""]
    cs = pack.get("costs") or {}
    if cs.get("day"):
        c, ss = cs["day"], cs["since_start"]
        L += ["## Real-world costs (not taken from the returns above)", "",
              f"- Today: bought and sold Rs {c['turnover']:,.0f} in total (Rs {c['intraday_value']:,.0f} of it bought "
              f"and sold the same day). Taxes and charges Rs {c['charges_total']:,.0f} (securities transaction tax "
              f"Rs {c['charges']['stt']:,.0f}, stamp duty Rs {c['charges']['stamp']:,.0f}, exchange, SEBI, GST and "
              f"depository Rs {c['charges']['exchange'] + c['charges']['sebi'] + c['charges']['gst'] + c['charges']['dp']:,.0f}).",
              f"- Income tax on today's booked profit (estimate): Rs {c['tax']:,.0f} (short-term gain Rs "
              f"{c['short_term_gain']:,.0f} at 20%, same-day profit Rs {c['intraday_gain']:,.0f} at 30%).",
              f"- Total real cost today Rs {c['total']:,.0f}; since the start Rs {ss['total']:,.0f} over {cs['days']} day(s).",
              f"- A switch from one stock to another costs about {costs.switch_cost_pct():.2f}% in taxes and charges "
              "alone, before price slippage.", ""]
    rc = pack.get("report_card") or []
    if rc:
        L += ["## Report card (each analyst's own paper portfolio on the same money)", "",
              "| analyst | team | today | since start | trades today | real cost today | led / used today |",
              "|---|---|---|---|---|---|---|"]
        for r in rc:
            L.append(f"| {r['name']} | {r['team']} | {_f(r['today_pct'])} | {_f(r['since_start_pct'])} | "
                     f"{r['trades_today']} | Rs {r['costs_today']:,.0f} | {r['led_today']} / {r['used_today']} |")
        L += [f"| The company (what the bot did) | | {_f(s['desk_pct'])} | {_f(s.get('company_since_start_pct'))} | "
              f"{s['trades']} | Rs {(cs.get('day') or {}).get('total', 0):,.0f} | |",
              f"| NIFTY 50 | | {_f(s['nifty_pct'])} | {_f(s.get('nifty_since_start_pct'))} | | | |", ""]
    sc = pack.get("scorecard") or {}
    if sc:
        L += ["## Rule scorecard (3-bar edge vs NIFTY, all days of this bot, AI decisions only)", "",
              "| rule | status | followed: n / days / edge | saw it, did not follow: n / edge | verdict |",
              "|---|---|---|---|---|"]
        st = {r["id"]: r["status"] for r in pack["playbook"]}
        for rid, v in sc.items():
            a, b = v["followed"], v["not_followed"]
            L.append(f"| {rid} | {st.get(rid, '')} | {a['n']} / {a['days']} / {_f(a['edge_pct'])} | "
                     f"{b['n']} / {_f(b['edge_pct'])} | {v['verdict']} |")
        L.append("")
    L += ["## Decisions", "",
          "Times are bar start times (IST); the decision used that bar's close and traded at the next bar's open. "
          "Each decision has two parts. **What it knew** is only information available at that bar's close. "
          "**Outcome** is hindsight: use it to test a rule across days, not to blame one call.", ""]
    for x in pack["decisions"]:
        k, c = x["knew"], x["chose"]
        n = k["nifty"]
        L += [f"### {x['time'][11:]} · {c['winner_name']} · by {c['by'] or 'unknown'}", "", "What it knew:",
              f"- NIFTY {n['close']:,.1f}, today {n['today_pct']:+.2f}%, {'above' if n['above_50_bar_avg'] else 'below'} its 50-bar average."]
        if k["mood"]:
            top = sorted(k["mood"]["scores"].items(), key=lambda kv: -abs(kv[1]["score"]))[:5]
            at = k["mood"]["read_at"]
            L.append(f"- Mood (read {at[11:] if at[:10] == x['time'][:10] else at}): "
                     + "; ".join(f"{sym} {m['score']:+.1f} {m['why']}" for sym, m in top))
        else:
            L.append("- Mood: none read yet.")
        for a in k["agents"]:
            prop = ", ".join(f"{sym} {w:.2f}" for sym, w in a["proposal"].items()) or "cash"
            L.append(f"- {a['name']}: {prop}; 2-day record {_f(a['record_2d_pct'])}" + (f". Case: {a['case']}" if a["case"] else ""))
        if k["rules_shown"]:
            L.append(f"- Coach rules shown: {', '.join(k['rules_shown'])}")
        tg = ", ".join(f"{sym} {w:.2f}" for sym, w in c["targets"].items()) or "cash"
        L += [f"- Chose {c['winner_name']} → {tg}"
              + (f"; confidence {c['confidence']}" if c["confidence"] is not None else "")
              + (f"; rules used {', '.join(c['rules_used'])}" if c["rules_used"] else "") + ".",
              f"- Reason: {c['reason']}", "", "Outcome (hindsight, % from this bar's close):", "",
              "| next | desk | NIFTY | " + " | ".join(desk.AGENT_IDS) + " |",
              "|---" * (3 + len(desk.AGENT_IDS)) + "|"]
        for h, o in x["outcome"].items():
            L.append(f"| {h} bar{'s' if h != '1' else ''} | {_f(o['desk'], '')} | {_f(o['nifty'], '')} | "
                     + " | ".join(_f(o.get(a), "") for a in desk.AGENT_IDS) + " |")
        L.append("")
    return "\n".join(L)


def write_review(pack: dict) -> Path:
    folder = coach_dir() / "reviews"
    folder.mkdir(parents=True, exist_ok=True)
    md = folder / f"{pack['day'] or 'none'}.md"
    md.write_text(review_markdown(pack), encoding="utf-8")
    md.with_suffix(".json").write_text(json.dumps(pack, indent=1, ensure_ascii=False), encoding="utf-8")
    return md


def compare_styles(p: desk.Panel, days: int, capital: float = 500_000) -> dict:
    """Replay the last `days` trading days without AI: one winner (the desk's way) vs a team mix of all agents
    (equal, or weighted by positive two-day records). Returns % return and trades per style, plus NIFTY."""
    start = max(5 * desk.BARS_PER_DAY, len(p) - days * desk.BARS_PER_DAY)
    s0 = max(0, start - desk.RECORD_BARS - 1)
    p = base_panel(p)
    sh = desk.shadows(p, capital, start=s0, agents=desk.OLD_IDS)
    bt = desk.backtest(p, capital, start, agents=desk.OLD_IDS)
    out = {"days": days, "nifty_pct": bt["market_pct"],
           "one winner": {"pct": bt["return_pct"], "trades": len(bt["sim"]["trades"])}}
    for name in ("team equal", "team by record"):
        targets = {}
        for t in range(start, len(p)):
            if name == "team equal":
                w = {a: 1 / len(desk.OLD_IDS) for a in desk.OLD_IDS}
            else:
                recs = {a: desk.record(sh["agents"][a]["sim"], s0, t) for a in desk.OLD_IDS}
                pos = {a: max(0.0, r) for a, r in recs.items() if r is not None}
                w = {a: v / sum(pos.values()) for a, v in pos.items()} if sum(pos.values()) > 0 else {}
            mix: dict[str, float] = {}
            for a, wa in w.items():
                for s, x in sh["agents"][a]["proposals"][t].items():
                    mix[s] = mix.get(s, 0) + wa * x
            targets[t] = {s: min(x, desk.MAX_WEIGHT) for s, x in mix.items() if x > 0.01}
        sim = desk.simulate(p, targets, capital, start)
        out[name] = {"pct": round((sim["equity"][-1]["value"] / capital - 1) * 100, 2), "trades": len(sim["trades"])}
    return out


def pick_bot(db) -> dict | None:
    bots = db.list_desks()
    return next((b for b in bots if b["status"] == "running"), None) or next(iter(bots), None)


def main(argv: list[str] | None = None) -> int:
    import argparse

    from .store import default_store
    ap = argparse.ArgumentParser(prog="python -m purple_api.coach")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("review", help="write coach/reviews/<day>.md and .json")
    r.add_argument("--day")
    r.add_argument("--bot")
    rp = sub.add_parser("report", help="join the coach's notes (JSON file) with the day's numbers into reports.json")
    rp.add_argument("--notes", required=True)
    rp.add_argument("--day")
    rp.add_argument("--bot")
    sub.add_parser("check", help="validate playbook.md")
    c = sub.add_parser("compare", help="replay one winner vs team mixes (no AI)")
    c.add_argument("--days", type=int, nargs="*", default=[40, 20, 10])
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if a.cmd == "check":
        path = coach_dir() / "playbook.md"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        rules = parse_playbook(text)
        errs = check(rules, text)
        for rr in live_rules(rules):
            print(f"{rr['id']} [{rr['status']}, {rr['added']}] {rr['text']}")
        print(f"{len(live_rules(rules))} live rules, {sum(r['status'] == 'retired' for r in rules)} retired.")
        for e in errs:
            print("ERROR:", e)
        return 1 if errs else 0
    db = default_store()
    if a.cmd == "compare":
        p = load_panel(db)
        for d in a.days:
            r = compare_styles(p, d)
            print(f"{d} days (NIFTY {r['nifty_pct']:+.2f}%): " + "; ".join(
                f"{k} {v['pct']:+.2f}% ({v['trades']} trades)" for k, v in r.items() if isinstance(v, dict)))
        return 0
    bot = db.get_desk(a.bot) if a.bot else pick_bot(db)
    if not bot:
        print("No desk bot in the database yet.")
        return 1
    pack = build_review(db, bot, a.day)
    if a.cmd == "report":
        try:
            rep = make_report(pack, json.loads(Path(a.notes).read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            print("ERROR:", e)
            return 1
        print(save_report(rep))
        return 0
    print(write_review(pack))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
