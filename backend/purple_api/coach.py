"""Claude coaches the bot: a daily review pack, a short playbook the AI chief reads, and a scorecard per rule.

Claude never runs inside the live loop. After a trading day a Claude Code session (the /coach-bot command) reads the
review pack, judges each decision on what the desk knew at the time, and edits `purple/coach/playbook.md`. The chief
(Gemini, every 30 minutes) reads the active rules as guidance inside <data> tags; the hard caps in desk.parse_chief
stay authoritative. Each chief decision lists the rule ids it followed (`rules_used`), so the scorecard can compare
decisions that followed a rule with decisions that saw it and did not.

CLI (no server needed, reads the same database):
    python -m purple_api.coach review [--day YYYY-MM-DD]   writes coach/reviews/<day>.md and .json
    python -m purple_api.coach check                        validates playbook.md and lists the active rules
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from . import desk

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

def load_panel(db) -> desk.Panel:
    return desk.align({s: db.get_market_bars(s, desk.INTERVAL) for s in desk.UNIVERSE},
                      db.get_market_bars(desk.MARKET, desk.INTERVAL))


def run_book(db, bot: dict, p: desk.Panel) -> tuple[dict, int, dict]:
    """The bot's own portfolio replayed from its stored decisions. Returns (sim, start index, decisions)."""
    start = p.times.index(bot["start_time"]) if bot["start_time"] in p.times else \
        next((i for i, t in enumerate(p.times) if t >= bot["start_time"]), len(p) - 1)
    ds = db.get_decisions(f"desk:{bot['id']}")
    idx = {t: i for i, t in enumerate(p.times)}
    targets = {idx[t]: d["targets"] for t, d in ds.items() if t in idx}
    notes = {idx[t]: d["winner"] for t, d in ds.items() if t in idx}
    return desk.simulate(p, targets, bot["capital"], start, notes), start, ds


def mood_index(p: desk.Panel, ms: dict[str, dict]) -> dict[int, dict[str, float]]:
    out = {}
    for ts, m in ms.items():
        i = max((i for i, t in enumerate(p.times) if t <= ts), default=None)
        if i is not None:
            out[i] = {s: v["score"] for s, v in m["scores"].items()}
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


def scorecard(p: desk.Panel, book: dict, start: int, ds: dict, rules: list[dict]) -> dict[str, dict]:
    """Per rule: 3-bar edge vs NIFTY (desk minus NIFTY, %) of AI decisions that cited it vs those that saw it and
    did not. Decisions decided by the track record are left out (the judge does not read rules)."""
    idx = {t: i for i, t in enumerate(p.times)}
    edges = {}
    for ts, d in ds.items():
        if ts in idx and d.get("by") != "record":
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
    names = {a["id"]: a["name"] for a in desk.AGENTS}
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
    s0 = max(0, i0 - desk.RECORD_BARS - 3 * desk.BARS_PER_DAY)
    ms = db.get_decisions(f"deskmood:{bot['id']}")
    sh = desk.shadows(p, bot["capital"], mood_index(p, ms), start=s0)
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
        "by_ai": sum(1 for t in todays if ds[t].get("by") != "record"),
        "winners": {names[a]: n for a, n in wins.most_common()}, "trades": len(trades),
        "bought": sum(tr["value"] for tr in trades if tr["side"] == "BUY"),
        "sold": sum(tr["value"] for tr in trades if tr["side"] == "SELL"),
        "day_complete": p.times[last_bar][11:] >= "15:15",  # Yahoo sometimes adds a 15:30 stub bar
    }
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
          f"- Desk {_f(s['desk_pct'])} vs NIFTY 50 {_f(s['nifty_pct'])} (previous close to last bar"
          f"{'' if s['day_complete'] else ', day not finished'}).",
          f"- {s['decisions']} decisions ({s['by_ai']} by AI). Winners: "
          + ", ".join(f"{a} {n}" for a, n in s["winners"].items()) + ".",
          f"- {s['trades']} trades: bought Rs {s['bought']:,.0f}, sold Rs {s['sold']:,.0f}.", ""]
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
    sub.add_parser("check", help="validate playbook.md")
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
    bot = db.get_desk(a.bot) if a.bot else pick_bot(db)
    if not bot:
        print("No desk bot in the database yet.")
        return 1
    pack = build_review(db, bot, a.day)
    print(write_review(pack))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
