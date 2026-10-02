import json
import time

import pytest
from fastapi.testclient import TestClient

from purple_api import agent_core, superagent as sa
from purple_api.engine import _Ctx, evaluate, run_backtest
from purple_api.main import create_app
from purple_api.sample import synthetic_bars
from purple_api.schema import Strategy
from purple_api.store import Store


class TeamProvider:
    """Answers each role by its system prompt; the manager follows a scripted action list."""
    name, model = "fake", "fake-1"

    def __init__(self, actions=("BUY", "HOLD", "SELL")):
        self.actions = list(actions)
        self.i = 0
        self.calls = 0

    def status(self):
        return {"provider": self.name, "model": self.model, "available": True, "detail": "test"}

    def complete(self, system, messages):
        self.calls += 1
        if "Bull Researcher" in system:
            return json.dumps({"argument": "RSI neutral, close above EMA10."})
        if "Bear Researcher" in system:
            return json.dumps({"argument": "Death-cross regime."})
        a = self.actions[self.i % len(self.actions)]
        self.i += 1
        return json.dumps({"action": a, "confidence": 0.7, "reason": f"scripted {a}"})


@pytest.fixture
def setup():
    p = TeamProvider()
    c = TestClient(create_app(store=Store(":memory:"), provider=p))
    ds = c.get("/api/datasets").json()[0]
    return c, p, ds


def wait(c, jid):
    for _ in range(200):
        j = c.get(f"/api/superagent/jobs/{jid}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_catalog_rule_bots_are_valid():
    for bid in sa.RULE_BOTS:
        st = sa.rule_strategy(bid)
        assert st is not None and st.questions == []
    ids = [a["id"] for a in sa.catalog()]
    assert ids[:2] == ["tradingagents-original", "tradingagents"] and "crewai-stock-analysis" in ids


def test_rule_bot_runs_on_sample(setup):
    c, _, ds = setup
    for bid in sa.RULE_BOTS:
        r = c.post("/api/superagent/run", json={"agent_id": bid, "dataset_id": ds["id"]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kind"] == "rules" and body["result"]["metrics"]["bars"] == ds["rows"]


def test_research_agent_not_runnable(setup):
    c, _, ds = setup
    r = c.post("/api/superagent/run", json={"agent_id": "crewai-stock-analysis", "dataset_id": ds["id"]})
    assert r.status_code == 409


def test_unavailable_analysis_rejected(setup):
    c, _, ds = setup
    r = c.post("/api/superagent/run", json={"agent_id": "tradingagents", "dataset_id": ds["id"], "analyses": ["market", "news"]})
    assert r.status_code == 422


def test_ai_team_job_and_next_open_fills(setup):
    c, p, ds = setup
    r = c.post("/api/superagent/run", json={"agent_id": "tradingagents", "dataset_id": ds["id"], "days": 4})
    j = wait(c, r.json()["job"]["id"])
    assert j["status"] == "done", j["error"]
    res = j["result"]
    assert [d["action"] for d in res["decisions"]] == ["BUY", "HOLD", "SELL", "BUY"]  # last-day BUY can't fill
    t = res["trades"][0]
    dates = [d["date"] for d in res["decisions"]]
    assert t["entry_date"] == dates[1] and t["exit_date"] == dates[3]  # each decision fills next open
    assert p.calls == 12  # 3 model calls per day
    # cached: re-running does not call the model again
    r2 = c.post("/api/superagent/run", json={"agent_id": "tradingagents", "dataset_id": ds["id"], "days": 4})
    assert wait(c, r2.json()["job"]["id"])["status"] == "done" and p.calls == 12


def test_invalid_actions_become_hold():
    def fake(system, user):
        if "Trader" in system:
            return json.dumps({"action": "SELL", "confidence": 2, "reason": "x"})
        return json.dumps({"argument": "y"})
    d = agent_core.run_team("report", "INFY", False, fake)
    assert d["action"] == "HOLD" and d["confidence"] == 1.0 and d["notes"]


def test_market_snapshot_has_no_lookahead():
    bars = synthetic_bars(400)
    assert agent_core.market_snapshot(bars, 300) == agent_core.market_snapshot(bars[:301], 300)


def test_synthetic_series_extends_with_identical_prefix():
    a, b = synthetic_bars(750), synthetic_bars(760)
    assert [x.__dict__ for x in a] == [x.__dict__ for x in b[:750]]


def test_trade_from_blocks_earlier_signals():
    st = sa.rule_strategy("ta-macd-momentum")
    bars = synthetic_bars(400)
    res = run_backtest(st, bars, trade_from=300)
    assert all(t["entry_date"] > bars[300].date for t in res["trades"])
    assert res["equity"][0]["date"] == bars[300].date and res["metrics"]["start_equity"] == 100000


def test_paper_rules_account_moves_forward(setup):
    c, _, ds = setup
    v = c.post("/api/superagent/paper", json={"agent_id": "ta-ema-momentum", "dataset_id": ds["id"], "capital": 50000}).json()
    assert v["result"]["metrics"]["start_equity"] == 50000 and v["today"]["action"] in ("BUY", "HOLD")
    pid, d0 = v["account"]["id"], v["latest_date"]
    for _ in range(5):
        v = c.post(f"/api/superagent/paper/{pid}/next-day").json()
    assert v["latest_date"] > d0 and len(v["result"]["equity"]) == 6


def test_paper_ai_account_decides_pending_days(setup):
    c, p, ds = setup
    v = c.post("/api/superagent/paper", json={"agent_id": "tradingagents", "dataset_id": ds["id"]}).json()
    pid = v["account"]["id"]
    assert v["pending_days"] == [v["latest_date"]]
    c.post(f"/api/superagent/paper/{pid}/next-day")
    j = c.post(f"/api/superagent/paper/{pid}/decide").json()["job"]
    assert j["total"] == 2 and wait(c, j["id"])["status"] == "done"
    v = c.get(f"/api/superagent/paper/{pid}").json()
    assert v["pending_days"] == [] and v["today"]["action"] in ("BUY", "SELL", "HOLD")
    assert [d["action"] for d in v["decisions"]] == ["BUY", "HOLD"]
    assert c.delete(f"/api/superagent/paper/{pid}").json()["ok"]


def test_exported_rules_script_matches_engine(setup):
    c, _, _ = setup
    for bid in sa.RULE_BOTS:
        code = c.get("/api/superagent/export", params={"agent_id": bid, "symbol": "infy"}).json()["code"]
        ns: dict = {"__name__": "exported"}
        exec(compile(code, "exported.py", "exec"), ns)  # our own generated code, in the test only
        assert ns["SYMBOL"] == "INFY" and ns["DRY_RUN"] is True
        st = sa.rule_strategy(bid)
        bars = synthetic_bars(400)
        script_bars = [ns["Bar"](**b.__dict__) for b in bars]
        ctx = _Ctx(bars=bars)
        for t in range(200, 400, 7):
            want = evaluate(ctx, st.entry, t)
            got = ns["signal"](script_bars[: t + 1]) == "BUY"
            assert want == got, (bid, t)


def test_exported_rules_script_exit_signal_matches_engine(setup):
    c, _, _ = setup
    bars = synthetic_bars(500)
    dates = [b.date for b in bars]
    for bid in sa.RULE_BOTS:
        ns: dict = {"__name__": "exported"}
        exec(compile(c.get("/api/superagent/export", params={"agent_id": bid}).json()["code"], "x.py", "exec"), ns)
        sb = [ns["Bar"](**b.__dict__) for b in bars]
        for t in run_backtest(sa.rule_strategy(bid), bars)["trades"]:
            if t["open"]:
                continue
            k = dates.index(t["exit_date"]) - 1  # signal bar: the close before the exit fill
            assert ns["signal"](sb[: k + 1], t["entry_date"], t["entry_price"]) == "SELL", (bid, t)
            if k - 1 >= dates.index(t["entry_date"]):
                assert ns["signal"](sb[:k], t["entry_date"], t["entry_price"]) == "HOLD", (bid, t)


def test_exported_team_script_compiles(setup):
    c, _, _ = setup
    out = c.get("/api/superagent/export", params={"agent_id": "tradingagents", "symbol": "TCS"}).json()
    ns: dict = {"__name__": "exported"}
    exec(compile(out["code"], "team.py", "exec"), ns)
    assert ns["MODEL_DEFAULT"] == "fake-1" and "run_team" in ns and out["filename"].endswith("_tcs.py")
