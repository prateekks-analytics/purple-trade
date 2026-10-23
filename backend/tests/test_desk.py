import json
import time
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from purple_api import coach, desk, desk_routes, market, news
from purple_api.main import create_app
from purple_api.sample import synthetic_bars
from purple_api.store import Store

from test_api import FakeProvider


def bars30(n: int, seed_shift: float = 0.0, day0=datetime(2026, 9, 1)) -> list:
    """n synthetic 30-minute bars, 13 per weekday session from 09:15 IST."""
    base, out, d = synthetic_bars(n), [], day0
    while len(out) < n:
        if d.weekday() < 5:
            for k in range(desk.BARS_PER_DAY):
                if len(out) == n:
                    break
                b = base[len(out)]
                t = (d.replace(hour=9, minute=15) + timedelta(minutes=30 * k)).strftime("%Y-%m-%d %H:%M")
                out.append(replace(b, date=t, open=b.open + seed_shift, high=b.high + seed_shift,
                                   low=b.low + seed_shift, close=b.close + seed_shift))
        d += timedelta(days=1)
    return out


def panel(n=300):
    stocks = {s: bars30(n, i * 3.0) for i, s in enumerate(desk.UNIVERSE)}
    return desk.align(stocks, bars30(n))


def test_simulate_fills_next_open_and_charges_costs():
    p = panel(40)
    sim = desk.simulate(p, {5: {"RELIANCE.NS": 0.5}}, 100_000, start=0, notes={5: "momentum"})
    buy = sim["trades"][0]
    assert buy["time"] == p.times[6] and buy["side"] == "BUY" and buy["why"] == "momentum"
    assert buy["price"] == round(p.bars["RELIANCE.NS"][6].open * 1.0005, 2)
    assert 45_000 < buy["value"] <= 50_000 and len(sim["equity"]) == 40
    sim2 = desk.simulate(p, {5: {"RELIANCE.NS": 0.5}, 10: {}}, 100_000)
    assert [t["side"] for t in sim2["trades"]] == ["BUY", "SELL"] and not sim2["holdings"]


def test_every_agent_proposes_valid_weights_and_backtest_runs():
    p = panel()
    sh = desk.shadows(p, 500_000, moods={60: {"INFY.NS": 0.8, "TCS.NS": -0.5}})
    for a in desk.AGENT_IDS:
        for w in sh["agents"][a]["proposals"].values():
            assert sum(w.values()) <= 1.0 + 1e-9 and all(0 < x <= desk.MAX_WEIGHT for x in w.values())
    assert "TCS.NS" not in sh["agents"]["news"]["proposals"][100]
    bt = desk.backtest(p, 500_000, 5 * desk.BARS_PER_DAY)
    assert set(bt["winners"].values()) <= set(desk.AGENT_IDS) and bt["sim"]["equity"][0]["value"] == 500_000
    assert desk.weekly(p, bt["sim"], 5 * desk.BARS_PER_DAY, 500_000)


def test_parse_chief_validates_the_ai_answer():
    props = {"momentum": {"INFY.NS": 0.32}}
    got = desk.parse_chief('ok {"winner":"momentum","targets":{"infy":0.9,"XYZ":0.2,"TCS.NS":0.3},'
                           '"debate":[{"agent":"momentum","case":"strong"},{"agent":"hacker","case":"x"}],'
                           '"reason":"Buy IT.","confidence":70}', props)
    assert got["targets"] == {"INFY.NS": 0.35, "TCS.NS": 0.3} and [d["agent"] for d in got["debate"]] == ["momentum"]
    assert desk.parse_chief('{"winner":"momentum"}', props)["targets"] == {"INFY.NS": 0.32}
    with pytest.raises(ValueError):
        desk.parse_chief('{"winner":"nobody"}', props)


def test_next_bar_close():
    ist = market.IST
    assert desk_routes.next_bar_close(datetime(2026, 10, 22, 10, 0, tzinfo=ist)).strftime("%H:%M") == "10:15"
    assert desk_routes.next_bar_close(datetime(2026, 10, 22, 15, 40, tzinfo=ist)).strftime("%d %H:%M") == "22 15:45"
    assert desk_routes.next_bar_close(datetime(2026, 10, 22, 15, 50, tzinfo=ist)).strftime("%d %H:%M") == "23 09:45"
    assert desk_routes.next_bar_close(datetime(2026, 10, 24, 12, 0, tzinfo=ist)).strftime("%a %H:%M") == "Mon 09:45"


@pytest.fixture
def client(monkeypatch):
    feed = {s: bars30(300, i * 3.0) for i, s in enumerate(desk.UNIVERSE)}
    feed[desk.MARKET] = bars30(300)
    monkeypatch.setattr(market, "intraday_bars", lambda s, interval="30m", range_="1mo", now=None: feed[s])
    monkeypatch.setattr(news, "headlines", lambda *a, **k: {"items": [{"title": "Good quarter"}], "notes": []})

    def make(provider):
        return TestClient(create_app(store=Store(":memory:"), provider=provider))
    return make


def test_start_bot_ai_chief_decides_and_view(client):
    mood = json.dumps({"INFY": {"score": 0.7, "why": "deal win"}})
    chief = json.dumps({"debate": [{"agent": "trend", "case": "uptrend"}], "winner": "trend",
                        "targets": {"INFY": 0.3}, "reason": "Buy Infosys.", "confidence": 60})
    prov = FakeProvider(mood, chief)
    prov.name = "gemini"
    c = client(prov)
    assert c.get("/api/desk").json()["bot"] is None
    v = c.post("/api/desk", json={"capital": 500000, "days": 7}).json()
    assert v["bot"]["status"] == "running" and v["value"] == 500000
    c.post("/api/desk/decide")
    v = c.get("/api/desk").json()
    d = v["decisions"][0]
    assert d["winner"] == "trend" and d["targets"] == {"INFY": 0.3} and d["by"].startswith("gemini")
    assert v["mood"]["scores"]["INFY"]["score"] == 0.7 and [a["id"] for a in v["agents"]][-1] == "core" and len(v["agents"]) == len(desk.AGENT_IDS) + 1
    assert v["core"]["on"] is False  # no daily prices in this test: the agents trade
    assert "<data>" in prov.calls[0][-1]["content"]
    assert c.post("/api/desk/stop").json()["bot"]["status"] == "stopped"


def test_without_ai_the_track_record_decides(client):
    c = client(FakeProvider())  # name "fake": not a background AI
    c.post("/api/desk", json={"capital": 300000, "days": 0})
    c.post("/api/desk/decide")
    d = c.get("/api/desk").json()["decisions"][0]
    assert d["by"] == "record" and d["winner"] in desk.AGENT_IDS and "No AI answered" in d["reason"]


def test_backtest_endpoint(client):
    r = client(FakeProvider()).get("/api/desk/backtest?days=10").json()
    assert r["capital"] == 500000 and len(r["agents"]) == len(desk.OLD_IDS) and r["series"] and "weeks_beat" in r


# ---------- Claude coaches the bot ----------

PLAYBOOK = """# playbook
## R1 | active | added 2026-10-20
Rule: Prefer cash when NIFTY is below its 50-bar average and down more than 0.5% today.
Why: Momentum lost money on falling days.

## R2 | trial | added 2026-10-21
Rule: Do not switch winners twice in a row.
Why: Churn cost fees.

## R3 | retired | added 2026-10-19 | retired 2026-10-21
Rule: Always follow the news agent.
Why: Was wrong.
"""


@pytest.fixture(autouse=True)
def coach_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PURPLE_COACH_DIR", str(tmp_path / "coach"))
    return tmp_path / "coach"


def write_playbook(folder, text=PLAYBOOK):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "playbook.md").write_text(text, encoding="utf-8")


def test_playbook_parse_render_retire_and_check(coach_dir):
    write_playbook(coach_dir)
    rules = coach.read_playbook()
    assert [(r["id"], r["status"]) for r in rules] == [("R1", "active"), ("R2", "trial"), ("R3", "retired")]
    assert rules[2]["retired"] == "2026-10-21" and [r["id"] for r in coach.live_rules()] == ["R1", "R2"]
    assert coach.parse_playbook(coach.render_playbook(rules)) == rules
    coach.retire("r2", today="2026-10-22")
    assert [r["id"] for r in coach.live_rules()] == ["R1"]
    with pytest.raises(KeyError):
        coach.retire("R3")
    text = coach.render_playbook(rules * 1) + "## R9 | maybe | added x\n"
    assert any("headings" in e for e in coach.check(coach.parse_playbook(text), text))
    many = [{**rules[0], "id": f"R{i}"} for i in range(11)]
    assert any("at most 10" in e for e in coach.check(many, coach.render_playbook(many)))


def test_chief_prompt_carries_the_playbook_as_data_and_rules_used_is_validated():
    p = panel(120)
    mkt = desk.features(p.market)
    rules = coach.parse_playbook(PLAYBOOK)[:2]
    text = desk.chief_prompt(p.times[100], {}, {}, [], 500_000, mkt, 100, None, [], rules)
    line = text.splitlines()[-1]
    assert line.startswith("<data>Coach playbook: R1: Prefer cash") and "R2 (trial):" in line and line.endswith("</data>")
    assert "Coach playbook" not in desk.chief_prompt(p.times[100], {}, {}, [], 500_000, mkt, 100, None, [])
    got = desk.parse_chief('{"winner":"guard","rules_used":["r1","R9","R1",3]}', {"guard": {}}, ["R1", "R2"])
    assert got["rules_used"] == ["R1"]
    assert desk.parse_chief('{"winner":"guard","rules_used":"R1"}', {"guard": {}}, ["R1"])["rules_used"] == []


def test_live_decision_records_rules_shown_and_used(client, coach_dir):
    write_playbook(coach_dir)
    chief = json.dumps({"winner": "guard", "targets": {}, "reason": "Stay in cash.", "rules_used": ["R1", "R3"]})
    prov = FakeProvider(json.dumps({}), chief)
    prov.name = "gemini"
    c = client(prov)
    c.post("/api/desk", json={"capital": 500000, "days": 7})
    c.post("/api/desk/decide")
    assert "<data>Coach playbook: R1" in prov.calls[1][-1]["content"] and "R3" not in prov.calls[1][-1]["content"]
    v = c.get("/api/desk").json()
    assert v["decisions"][0]["rules_used"] == ["R1"]
    assert [r["id"] for r in v["coach"]["rules"]] == ["R1", "R2"] and v["coach"]["rules"][0]["score"]["verdict"] == "too early"
    assert [r["id"] for r in c.post("/api/desk/coach/rules/R1/retire").json()["rules"]] == ["R2"]
    assert c.post("/api/desk/coach/rules/R1/retire").status_code == 404


def seeded_bot(db, n=300):
    """A bot that started at bar 100 with an AI decision on every bar of four days; R1 cited on even bars."""
    for i, s in enumerate(desk.UNIVERSE):
        db.upsert_bars(s, desk.INTERVAL, bars30(n, i * 3.0))
    db.upsert_bars(desk.MARKET, desk.INTERVAL, bars30(n))
    p = coach.load_panel(db)
    bot = db.add_desk("test", 500_000, 0, p.times[104])
    for t in range(104, 104 + 4 * desk.BARS_PER_DAY):
        cited = t % 2 == 0
        db.save_decision(f"desk:{bot['id']}", p.times[t], {
            "winner": "trend" if cited else "guard", "targets": {"INFY.NS": 0.3} if cited else {},
            "reason": "r", "by": "gemini:x", "debate": [{"agent": "trend", "case": "uptrend"}],
            "records": {a: 0.1 for a in desk.AGENT_IDS}, "proposals": {"trend": {"INFY": 0.3}},
            "rules_shown": ["R1", "R2"], "rules_used": ["R1"] if cited else [], "confidence": 50})
    return p, bot


def test_review_pack_separates_knowledge_from_outcomes_and_scores_rules(coach_dir):
    write_playbook(coach_dir)
    db = Store(":memory:")
    p, bot = seeded_bot(db)
    day = p.times[104 + desk.BARS_PER_DAY][:10]
    pack = coach.build_review(db, bot, day, p)
    s = pack["summary"]
    assert pack["day"] == day and s["decisions"] == len(pack["decisions"]) > 0 and s["by_ai"] == s["decisions"]
    assert set(s["winners"]) <= {"Trend rider", "Risk guard"} and s["trades"] >= 1
    d = pack["decisions"][0]
    assert set(d) == {"time", "knew", "chose", "outcome"} and d["time"].startswith(day)
    assert {"nifty", "mood", "agents", "rules_shown"} == set(d["knew"]) and len(d["knew"]["agents"]) == len(desk.AGENT_IDS)
    assert d["knew"]["agents"][1]["case"] == "uptrend"
    o = d["outcome"]
    assert set(o) == {"1", "3", "13"} and set(o["3"]) == {"desk", "nifty", *desk.AGENT_IDS}
    # the 3-bar NIFTY outcome is exactly the market move from this bar's close
    t = p.times.index(d["time"])
    assert o["3"]["nifty"] == round((p.market[t + 3].close / p.market[t].close - 1) * 100, 3)
    sc = pack["scorecard"]
    assert sc["R1"]["followed"]["n"] > 4 and sc["R1"]["followed"]["days"] >= 2
    assert sc["R1"]["verdict"] in ("helping", "hurting", "no clear effect")
    assert sc["R2"]["followed"]["n"] == 0 and sc["R2"]["verdict"] == "too early"
    md = coach.write_review(pack)
    text = md.read_text(encoding="utf-8")
    assert md.name == f"{day}.md" and md.with_suffix(".json").exists()
    assert "## Day summary" in text and "What it knew:" in text and "Outcome (hindsight" in text and "| R1 |" in text
    # outcomes not yet known stay empty instead of guessing
    last = coach.build_review(db, bot, None, desk.Panel(p.times[:156], {k: v[:156] for k, v in p.bars.items()}, p.market[:156]))
    assert last["decisions"][-1]["outcome"]["13"]["desk"] is None


def test_review_endpoint_and_cli(client, coach_dir, monkeypatch, tmp_path):
    c = client(FakeProvider())
    assert c.get("/api/desk/review").status_code == 404
    db = c.app.state.store
    p, bot = seeded_bot(db)
    r = c.get("/api/desk/review").json()
    assert r["day"] == max(db.get_decisions(f"desk:{bot['id']}"))[:10] and r["decisions"]
    assert c.get("/api/desk/review?day=22-10-2026").status_code == 422
    r = c.get(f"/api/desk/review?day={p.times[110][:10]}&save=true").json()
    assert (coach_dir / "reviews" / f"{p.times[110][:10]}.md").exists() and r["saved_to"]
    file_db = tmp_path / "cli.sqlite3"
    seeded_bot(Store(file_db))
    monkeypatch.setenv("PURPLE_DB", str(file_db))
    assert coach.main(["review"]) == 0 and len(list((coach_dir / "reviews").glob("*.md"))) == 2
    write_playbook(coach_dir)
    assert coach.main(["check"]) == 0


def test_free_ai_chain_groq_first_then_gemini(monkeypatch):
    from purple_api.ai import providers as pv
    monkeypatch.delenv("PURPLE_AI_PROVIDER", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    chain = pv.default_provider()
    assert isinstance(chain, pv.ChainProvider) and (chain.name, chain.model) == ("groq", "openai/gpt-oss-120b")
    assert [p.name for p in chain.providers] == ["groq", "gemini"] and chain.status()["available"]

    class Down:
        name, model = "groq", "openai/gpt-oss-120b"
        def complete(self, s, m): raise pv.ProviderError("rate limit")
    class Up:
        name, model = "gemini", "gemini-3.5-flash"
        def complete(self, s, m): return '{"winner":"guard"}'
    c = pv.ChainProvider([Down(), Up()])
    assert c.complete("s", []) == '{"winner":"guard"}' and (c.name, c.model) == ("gemini", "gemini-3.5-flash")
    with pytest.raises(pv.ProviderError, match="groq: rate limit"):
        pv.ChainProvider([Down()]).complete("s", [])
    monkeypatch.delenv("GROQ_API_KEY")
    assert isinstance(pv.default_provider(), pv.GeminiProvider)  # unchanged without a Groq key


def test_compare_styles_reports_each_way_of_choosing():
    r = coach.compare_styles(panel(), 10)
    assert set(r) == {"days", "nifty_pct", "one winner", "team equal", "team by record"}
    assert all(isinstance(r[k]["pct"], float) and r[k]["trades"] >= 0 for k in ("one winner", "team equal", "team by record"))


def test_chief_aims_for_maximum_return_not_just_the_index():
    assert "highest return" in desk.CHIEF_SYSTEM and "only the minimum" in desk.CHIEF_SYSTEM
    assert "highest return" in desk.LESSON_SYSTEM


def test_guard_check_rules():
    held = ["INFY.NS", "TCS.NS"]
    hit = desk.guard_check(held, 99.2, [100.0, 99.8], {"INFY.NS": 10, "TCS.NS": 10}, {"INFY.NS": 10, "TCS.NS": 10})
    assert hit["kind"] == "market" and hit["symbols"] == held and "0.8%" in hit["reason"]
    hit = desk.guard_check(held, 100, [100.2], {"INFY.NS": 94.9, "TCS.NS": 99}, {"INFY.NS": 100, "TCS.NS": 100})
    assert hit["kind"] == "stock" and hit["symbols"] == ["INFY.NS"]
    assert desk.guard_check(held, 99.5, [100.0], {"INFY.NS": 96}, {"INFY.NS": 100}) is None  # small dips: hold
    assert desk.guard_check([], 50, [100], {}, {}) is None


def test_guard_sale_in_the_books():
    p = panel(40)
    sim = desk.simulate(p, {5: {"RELIANCE.NS": 0.5}}, 100_000, exits={8: [("RELIANCE.NS", 99.0, "crash guard")]})
    sell = sim["trades"][-1]
    assert sell["side"] == "SELL" and sell["why"] == "crash guard" and sell["price"] == round(99.0 * 0.9995, 2)
    assert not sim["holdings"] and sim["equity"][8]["value"] == sim["equity"][-1]["value"]  # cash from then on
    now = desk.simulate(p, {5: {"RELIANCE.NS": 0.5}}, 100_000, exits={len(p): [("RELIANCE.NS", 99.0, "crash guard")]})
    assert not now["holdings"] and now["trades"][-1]["time"] == "now"  # a sale in the bar still forming


def test_guard_in_the_live_loop(client, monkeypatch):
    c = client(FakeProvider())
    c.post("/api/desk", json={"capital": 500000, "days": 0})
    db = c.app.state.store
    bot = db.list_desks()[0]
    p = coach.load_panel(db)
    db.save_decision(f"desk:{bot['id']}", p.times[-1], {"winner": "trend", "targets": {"INFY.NS": 0.3}, "reason": "r",
                                                        "by": "record", "debate": [], "records": {}, "proposals": {}})
    last = datetime.strptime(p.times[-1], "%Y-%m-%d %H:%M")
    day = last + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    now = day.replace(hour=11, minute=2, tzinfo=market.IST)
    prices = {desk.MARKET: (99.0, [100.0, 99.6]), "INFY.NS": (50.0, [50.5])}
    monkeypatch.setattr(market, "recent_prices", lambda s, minutes=30, now=None: prices[s])
    c.app.state.desk_tick(now)
    ev = coach.guard_events(db, bot)
    assert len(ev) == 1 and ev[0]["kind"] == "market" and ev[0]["bar"] == day.strftime("%Y-%m-%d") + " 10:45"
    assert ev[0]["prices"] == {"INFY.NS": 50.0}
    book, _, _ = coach.run_book(db, bot, p)
    assert not book["holdings"]
    c.app.state.desk_tick(now + timedelta(minutes=1))
    assert len(coach.guard_events(db, bot)) == 1  # one market sale per day


def test_no_ai_meeting_while_the_guard_holds_cash(client):
    calls = []

    class Counting(FakeProvider):
        def complete(self, system, messages):
            calls.append(system)
            return super().complete(system, messages)
    c = client(Counting())
    c.post("/api/desk", json={"capital": 500000, "days": 0})
    db = c.app.state.store
    bot = db.list_desks()[0]
    p = coach.load_panel(db)
    bar = p.times[-1]
    db.save_decision(f"deskguard:{bot['id']}", bar[:10] + " 10:09:00",
                     {"bar": bar, "day": bar[:10], "kind": "market", "symbols": [], "prices": {},
                      "reason": "fell", "time": "10:09"})
    for _ in range(100):  # the launch decides the newest bar in a background thread: let it finish
        if bar in db.get_decisions(f"desk:{bot['id']}"):
            break
        time.sleep(0.05)
    db._q("DELETE FROM agent_decisions WHERE cache_key=? AND date=?", (f"desk:{bot['id']}", bar))
    calls.clear()
    c.post("/api/desk/decide")
    d = db.get_decisions(f"desk:{bot['id']}")[bar]
    assert d["by"] == "rule:guard" and d["targets"] == {} and "does not meet" in d["reason"]
    assert calls == []  # no AI meeting and no mood read


def daily_line(n, start=100.0, step=0.5, day0=datetime(2025, 1, 1)):
    from purple_api.engine import Bar
    out, d = [], day0
    while len(out) < n:
        if d.weekday() < 5:
            c = start + step * len(out)
            out.append(Bar(d.strftime("%Y-%m-%d"), c, c, c, c, 1000.0))
        d += timedelta(days=1)
    return out


def test_core_regime_picks_and_monthly_hold():
    from purple_api import leaders
    up, down = daily_line(260, step=1.0), daily_line(260, start=400, step=-1.0)
    day = "2026-02-01"
    assert leaders.regime(up, day)["on"] and not leaders.regime(down, day)["on"]
    assert leaders.regime(up[:100], day)["on"] is False  # not enough history: stay out
    daily = {f"S{k}.NS": daily_line(260, step=0.1 * k) for k in range(8)}
    assert leaders.strongest(daily, day) == ["S7.NS", "S6.NS", "S5.NS", "S4.NS", "S3.NS"]
    # no look-ahead: only closes before the day count
    assert leaders.strongest(daily, up[100].date) == leaders.strongest({s: r[:100] for s, r in daily.items()}, up[100].date)
    first = leaders.today(None, daily, up, up[230].date)
    assert first["on"] and first["refreshed"] == up[230].date and len(first["picks"]) == 5
    kept = leaders.today(first, daily, up, up[240].date)  # rankings may move; picks are held 21 days
    assert kept["picks"] == first["picks"] and kept["refreshed"] == first["refreshed"]
    later = leaders.today(first, daily, up, up[255].date)
    assert later["refreshed"] == up[255].date
    assert leaders.today(first, daily, down, day) == {"on": False, "picks": [], "refreshed": None,
                                                     "gap_pct": leaders.regime(down, day)["gap_pct"]}


def test_core_takes_over_in_an_uptrend(client, monkeypatch):
    from purple_api import leaders
    c = client(FakeProvider())
    db = c.app.state.store
    c.post("/api/desk", json={"capital": 500000, "days": 0})
    p = coach.load_panel(db)
    last_day = datetime.strptime(p.times[-1][:10], "%Y-%m-%d")
    day0 = last_day - timedelta(days=364)  # 260 weekdays ending the day before the last bar
    nifty = daily_line(260, step=1.0, day0=day0)
    assert nifty[-1].date < p.times[-1][:10]
    db.upsert_bars(desk.MARKET, "1d", nifty)
    monkeypatch.setattr(leaders, "WIDE", ["INFY.NS", "TCS.NS", "LT.NS", "SBIN.NS", "ITC.NS", "AXISBANK.NS"])
    for k, s in enumerate(leaders.WIDE):
        db.upsert_bars(s, "1d", daily_line(260, step=0.2 * (k + 1), day0=day0))
    bot = db.list_desks()[0]
    key = f"desk:{bot['id']}"
    db._q("DELETE FROM agent_decisions WHERE cache_key=?", (key,))
    c.post("/api/desk/decide")
    d = c.get("/api/desk").json()
    assert d["decisions"][0]["winner"] == "core" and d["decisions"][0]["by"] == "rule:core"
    assert set(d["decisions"][0]["targets"]) == {"AXISBANK", "ITC", "SBIN", "LT", "TCS"}
    assert d["core"]["on"] and d["agents"][-1]["proposal"] and "200-day" in d["decisions"][0]["reason"]


def test_every_analyst_in_the_company_proposes_valid_portfolios():
    p = panel()
    extra = bars30(300, 50.0)
    p = desk.align({**{s: b for s, b in p.bars.items()}, "TRENT.NS": extra}, p.market)
    daily = {s: daily_line(260, step=0.3 + 0.05 * i) for i, s in enumerate(desk.UNIVERSE)}
    daily[desk.MARKET] = daily_line(260, step=0.5)
    fund = {s: [{"type": k, "as_of": y, "value": v * (1 + 0.1 * i) * (2 if y == "2025-03-31" else 1)}
                for y in ("2024-03-31", "2025-03-31") for k, v in
                (("NetIncome", 10.0), ("TotalRevenue", 100.0), ("StockholdersEquity", 50.0), ("TotalDebt", 5.0))]
            for i, s in enumerate(desk.UNIVERSE)}
    ctx = {"daily": desk.daily_context(p, daily), "fund": desk.fundamental_scores(fund, "2026-10-01"),
           "social": {60: {"INFY.NS": 0.8, "TCS.NS": -0.6}}, "risky": {t: ["TRENT.NS"] for t in range(100, 300)}}
    sh = desk.shadows(p, 500_000, moods={60: {"INFY.NS": 0.8}}, ctx=ctx)
    assert set(sh["agents"]) == set(desk.AGENT_IDS)
    busy = set()
    for a in desk.AGENT_IDS:
        for t, w in sh["agents"][a]["proposals"].items():
            assert sum(w.values()) <= 1.0 + 1e-9 and all(0 < x <= desk.MAX_WEIGHT for x in w.values())
            assert a == "highbeta" or "TRENT.NS" not in w  # only the risk-taker trades outside the base 10
            if w:
                busy.add(a)
    assert {"growth", "quality", "social", "highbeta", "news"} <= busy
    assert "TCS.NS" not in sh["agents"]["social"]["proposals"][200]


def test_manager_combines_analysts_and_moods_split():
    props = {"growth": {"INFY.NS": 0.24}, "highbeta": {"TRENT.NS": 0.3}}
    got = desk.parse_chief('{"winner":"growth","uses":["growth","highbeta","ghost"],"targets":{"INFY":0.3,"TRENT":0.2}}',
                           props, allowed=desk.UNIVERSE + ["TRENT.NS"])
    assert got["targets"] == {"INFY.NS": 0.3, "TRENT.NS": 0.2} and got["uses"] == ["growth", "highbeta"]
    assert desk.parse_chief('{"winner":"growth","targets":{"TRENT":0.2}}', props)["targets"] == {}  # not allowed
    m = desk.parse_mood('{"INFY":{"news":0.5,"social":-0.4,"why":"x"},"TCS":{"score":0.2}}')
    assert m["INFY.NS"]["score"] == 0.5 and m["INFY.NS"]["social"] == -0.4 and m["TCS.NS"]["social"] == 0.2


def test_old_bot_twin_tracks_the_original_desk(client):
    c = client(FakeProvider())
    c.post("/api/desk", json={"capital": 500000, "days": 0})
    v = c.get("/api/desk").json()
    assert v["twin"]["value"] > 0 and isinstance(v["twin"]["return_pct"], float)
    db = c.app.state.store
    tw = coach.twin(db, db.list_desks()[0], coach.load_panel(db))
    assert tw["equity"][0]["value"] == 500000


def test_without_ai_only_the_original_five_are_followed(client):
    c = client(FakeProvider())
    c.post("/api/desk", json={"capital": 300000, "days": 0})
    c.post("/api/desk/decide")
    d = c.get("/api/desk").json()["decisions"][0]
    assert d["by"] == "record" and d["winner"] in desk.OLD_IDS


def test_manager_answer_with_names_or_a_mix_is_accepted():
    props = {"growth": {"INFY.NS": 0.24}, "quality": {"TCS.NS": 0.24, "INFY.NS": 0.24}, "guard": {}}
    a = desk.parse_chief('{"winner":"Quality investor","targets":{"TCS":0.3}}', props)
    assert a["winner"] == "quality"
    b = desk.parse_chief('{"winner":"mixed","uses":["Growth investor","quality"],"targets":{"INFY":0.3}}', props)
    assert b["winner"] == "growth" and b["uses"] == ["growth", "quality"]
    c = desk.parse_chief('{"winner":"combined","targets":{"TCS":0.2,"INFY":0.2}}', props)
    assert c["winner"] == "quality"  # overlaps most with the mix
    with pytest.raises(ValueError):
        desk.parse_chief('{"winner":"nobody","targets":{}}', props)


JOURNAL = """# Purple Desk coach journal

Intro text.

## 2026-10-22 · review of 2026-10-22
- Result: company +0.30% vs NIFTY -0.54%; 29 trades.
- Good calls: moved to cash early.
- Mistakes: churn.
  - two cash round trips
- Playbook: added R1 (trial).

## 2026-10-23 · review of 2026-10-23
- Summary: A quiet day. The new rule cut trading.
- Result: company +0.10% vs NIFTY +0.05%.
"""


def test_journal_parse_and_endpoint(client, coach_dir):
    entries = coach.parse_journal(JOURNAL)
    assert [e["day"] for e in entries] == ["2026-10-23", "2026-10-22"]  # newest first
    assert entries[0]["summary"] == "A quiet day. The new rule cut trading."
    assert [i["label"] for i in entries[0]["items"]] == ["Result"]  # the summary is not repeated as an item
    old = entries[1]
    assert old["summary"] is None and old["items"][2] == {"label": "Mistakes", "text": "churn. two cash round trips"}
    c = client(FakeProvider())
    assert c.get("/api/desk/journal").json() == {"reports": [], "entries": []}  # nothing yet
    coach_dir.mkdir(parents=True, exist_ok=True)
    (coach_dir / "journal.md").write_text(JOURNAL, encoding="utf-8")
    assert c.get("/api/desk/journal").json()["entries"] == entries


def test_real_costs_split_intraday_and_delivery_and_tax_profits():
    from purple_api import costs
    trades = [
        {"time": "2026-10-21 10:15", "symbol": "TCS", "side": "BUY", "qty": 10, "price": 1000.0, "value": 10000},
        {"time": "2026-10-22 09:45", "symbol": "TCS", "side": "SELL", "qty": 10, "price": 1100.0, "value": 11000},
        {"time": "2026-10-22 10:15", "symbol": "INFY", "side": "BUY", "qty": 5, "price": 2000.0, "value": 10000},
        {"time": "2026-10-22 11:15", "symbol": "INFY", "side": "SELL", "qty": 5, "price": 2020.0, "value": 10100},
    ]
    led = costs.ledger(trades)
    d1, d2 = led["2026-10-21"], led["2026-10-22"]
    assert d1["charges"]["stt"] == 10.0 and d1["charges"]["stamp"] == 1.5 and d1["tax"] == 0  # a delivery buy
    assert d2["intraday_value"] == 20100 and d2["delivery_value"] == 11000
    assert d2["short_term_gain"] == 1000 and d2["intraday_gain"] == 100
    assert d2["tax"] == 1000 * 0.20 + 100 * 0.30
    assert d2["charges"]["stt"] == round(11000 * 0.001 + 10100 * 0.00025, 2) and d2["charges"]["dp"] == costs.DP_PER_SELL
    sm = costs.summary(trades, "2026-10-22")
    assert sm["day"] == d2 and sm["since_start"]["total"] == round(d1["total"] + d2["total"], 2)
    assert 0.2 < costs.switch_cost_pct() < 0.25


def test_steady_hands_blocks_same_day_round_trips_and_small_reweights():
    p = panel(60)
    a, b = desk.UNIVERSE[0], desk.UNIVERSE[1]
    day2 = next(i for i, t in enumerate(p.times) if t[:10] != p.times[0][:10])
    targets = {day2: {a: 0.3}, day2 + 2: {}, day2 + 4: {a: 0.3, b: 0.3}, day2 + 6: {a: 0.35, b: 0.3}}
    free = desk.simulate(p, targets, 500_000, 0)
    steady = desk.simulate(p, targets, 500_000, 0, steady_from=p.times[0])
    sides = lambda sim: [(t["symbol"], t["side"]) for t in sim["trades"]]  # noqa: E731
    assert (desk.short(a), "SELL") in sides(free)  # without the limit: bought and sold the same day
    assert sides(steady) == [(desk.short(a), "BUY"), (desk.short(b), "BUY")]  # no sell; 0.30 -> 0.35 skipped


def test_coach_report_joins_notes_with_numbers_and_reaches_the_manager(coach_dir):
    pack = {"day": "2026-10-22", "bot": {"id": "b1", "capital": 500000},
            "summary": {"desk_pct": 0.3, "nifty_pct": -0.54, "twin_pct": 0.03, "company_rupees": 1500, "trades": 29},
            "costs": {"day": {"total": 1526.0}, "since_start": {"total": 1526.0}},
            "report_card": [{"id": "news", "name": "News analyst"}, {"id": "momentum", "name": "Momentum"},
                            {"id": "twin", "name": "Old bot"}]}
    notes = {"headline": "A small gain on a falling day.", "story": "The bot followed the news analyst most of the day.",
             "grades": {"news": {"grade": "strong", "trust": "more", "why": "Best result today."},
                        "momentum": {"grade": "weak", "trust": "less", "why": "Lost and traded a lot."}},
             "ideas": [{"title": "Trade less", "detail": "Hold longer.", "who": "coach"}]}
    with pytest.raises(ValueError):
        coach.make_report(pack, {**notes, "grades": {"news": notes["grades"]["news"]}})  # momentum missing
    with pytest.raises(ValueError):
        coach.make_report(pack, {**notes, "grades": {**notes["grades"], "nobody": notes["grades"]["news"]}})
    rep = coach.make_report(pack, notes)
    assert rep["numbers"]["company_rupees"] == 1500 and rep["costs"]["day"]["total"] == 1526.0
    coach.save_report(rep)
    coach.save_report({**rep, "headline": "Rewritten."})  # same bot and day: replaced, not added
    assert [r["headline"] for r in coach.read_reports()] == ["Rewritten."]
    assert coach.latest_report("b1", "2026-10-22 10:15") is None  # a decision only sees earlier days
    got = coach.latest_report("b1", "2026-10-23 09:15")
    mkt = desk.features(panel(30).market)
    prompt = desk.chief_prompt("2026-10-23 09:15", {"news": {}}, {"news": None}, [], 500000, mkt, 5, None, [],
                               None, got, 0.22)
    assert "news strong, trust more" in prompt and "momentum weak, trust less" in prompt
    assert "Rs 220 in taxes and charges" in prompt and "trading cost Rs 1,526" in prompt
