import json
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
    assert v["mood"]["scores"]["INFY"]["score"] == 0.7 and len(v["agents"]) == 5
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
    assert r["capital"] == 500000 and len(r["agents"]) == 5 and r["series"] and "weeks_beat" in r


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
    got = desk.parse_chief('{"winner":"guard","rules_used":["r1","R9","R1",3]}', {}, ["R1", "R2"])
    assert got["rules_used"] == ["R1"]
    assert desk.parse_chief('{"winner":"guard","rules_used":"R1"}', {}, ["R1"])["rules_used"] == []


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
    assert {"nifty", "mood", "agents", "rules_shown"} == set(d["knew"]) and len(d["knew"]["agents"]) == 5
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
