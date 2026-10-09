import json

import pytest
from fastapi.testclient import TestClient

from purple_api.ai import number_fidelity, propose
from purple_api.csvdata import CsvError, parse_csv
from purple_api.main import create_app
from purple_api.schema import Strategy
from purple_api.store import Store

RSI = {"kind": "indicator", "name": "rsi", "period": 14, "source": "close", "offset": 0}
GOOD = {"name": "RSI 10/90",
        "entry": {"kind": "compare", "left": RSI, "op": "==", "right": {"kind": "const", "value": 10}},
        "exit": {"kind": "compare", "left": RSI, "op": ">", "right": {"kind": "const", "value": 90}}}


class FakeProvider:
    name, model = "fake", "fake-1"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def status(self):
        return {"provider": self.name, "model": self.model, "available": True, "detail": "test"}

    def complete(self, system, messages):
        self.calls.append(messages)
        return self.replies.pop(0)


@pytest.fixture
def client():
    return TestClient(create_app(store=Store(":memory:"), provider=FakeProvider()))


# ---------- AI proposal ----------

def test_propose_valid_and_fidelity_ok():
    p = FakeProvider(json.dumps({"strategy": GOOD, "questions": [], "notes": "ok"}))
    r = propose("buy when RSI is 10 and sell above 90", None, [], p)
    assert r["ok"] and r["strategy"]["entry"]["op"] == "=="
    assert r["fidelity"] == []


def test_propose_repairs_once_then_succeeds():
    bad = json.dumps({"strategy": {**GOOD, "entry": {"kind": "compare", "left": RSI, "op": "=<"}}, "questions": []})
    p = FakeProvider(bad, json.dumps({"strategy": GOOD, "questions": [], "notes": ""}))
    r = propose("RSI 10 then 90", None, [], p)
    assert r["ok"] and r["attempts"] == 2 and len(p.calls) == 2


def test_propose_reports_failure_after_retry():
    p = FakeProvider("not json", "still not json")
    r = propose("whatever", None, [], p)
    assert not r["ok"] and "format" in r["error"]


def test_propose_null_strategy_with_questions():
    p = FakeProvider(json.dumps({"strategy": None, "questions": ["Short selling is not supported yet."]}))
    r = propose("short NIFTY on Fridays", None, [], p)
    assert r["ok"] and r["strategy"] is None and r["questions"]


def test_fidelity_flags_changed_threshold():
    s = Strategy.model_validate({**GOOD, "entry": {**GOOD["entry"], "right": {"kind": "const", "value": 30}}})
    warn = number_fidelity("buy when RSI is 10 and sell above 90", s)
    assert len(warn) == 1 and "10" in warn[0]


# ---------- CSV ----------

def test_parse_nse_style_export():
    raw = ('Date ,series ,OPEN ,HIGH ,LOW ,PREV. CLOSE ,ltp ,close ,vwap ,VOLUME \n'
           '03-Oct-2025,EQ,"1,510.00","1,525.50","1,500.10","1,505.00","1,520.00","1,521.30",1515.2,"1,234,567"\n'
           '01-Oct-2025,EQ,"1,490.00","1,512.00","1,488.00","1,480.00","1,505.00","1,505.00",1500.1,"987,654"\n')
    bars, warnings = parse_csv(raw.encode())
    assert [b.date for b in bars] == ["2025-10-01", "2025-10-03"]
    assert bars[1].close == 1521.30 and bars[1].volume == 1234567
    assert any("sorted" in w for w in warnings)


def test_parse_rejects_missing_columns_and_duplicates():
    with pytest.raises(CsvError, match="Missing"):
        parse_csv(b"date,price\n2025-01-01,1\n")
    with pytest.raises(CsvError, match="twice"):
        parse_csv(b"date,open,close\n2025-01-01,1,2\n2025-01-01,1,3\n2025-01-02,1,2\n")


# ---------- API flow ----------

def test_full_flow_draft_approve_backtest(client):
    sid = client.post("/api/strategies", json={"name": "t"}).json()["id"]
    body = {**GOOD, "exit": {"kind": "any", "items": [GOOD["exit"],
            {"kind": "compare", "left": {"kind": "position", "field": "pnl_pct"}, "op": "<=", "right": {"kind": "const", "value": -5}}]}}

    # questions block approval
    r = client.put(f"/api/strategies/{sid}/draft", json={**body, "questions": ["period?"]})
    assert r.status_code == 200 and not r.json()["review"]["validation"]["ok"]
    assert client.post(f"/api/strategies/{sid}/approve").status_code == 409

    client.put(f"/api/strategies/{sid}/draft", json=body)
    s = client.post(f"/api/strategies/{sid}/approve").json()
    assert len(s["versions"]) == 1
    # identical re-approval rejected (versions are immutable, no duplicates)
    assert client.post(f"/api/strategies/{sid}/approve").status_code == 409

    sample = client.get("/api/datasets").json()[0]
    assert sample["synthetic"] == 1
    run = client.post("/api/backtests", json={"strategy_id": sid, "dataset_id": sample["id"],
                                              "version_id": s["versions"][0]["id"]}).json()
    assert run["mode"] == "approved" and run["metrics"]["bars"] == sample["rows"]
    assert client.get(f"/api/strategies/{sid}/runs").json()[0]["id"] == run["id"]


def test_malformed_draft_rejected_with_readable_errors(client):
    sid = client.post("/api/strategies", json={}).json()["id"]
    r = client.put(f"/api/strategies/{sid}/draft", json={"entry": {"kind": "compare"}, "exit": {}})
    assert r.status_code == 422 and r.json()["detail"]["shape_errors"]


def test_upload_csv_and_dedupe(client):
    csv = b"date,open,high,low,close\n" + b"".join(
        f"2025-01-{d:02d},{100 + d},{102 + d},{99 + d},{101 + d}\n".encode() for d in range(1, 29))
    first = client.post("/api/datasets", files={"file": ("x.csv", csv)}, data={"symbol": "infy"}).json()
    assert first["symbol"] == "INFY" and first["rows"] == 28
    again = client.post("/api/datasets", files={"file": ("x.csv", csv)}).json()
    assert again["id"] == first["id"]


def test_ai_endpoint_keeps_draft_until_user_applies():
    prov = FakeProvider(json.dumps({"strategy": GOOD, "questions": ["RSI period?"], "notes": "n"}))
    c = TestClient(create_app(store=Store(":memory:"), provider=prov))
    sid = c.post("/api/strategies", json={}).json()["id"]
    r = c.post(f"/api/strategies/{sid}/ai", json={"message": "RSI is 10, sell above 90"}).json()
    assert r["strategy"]["questions"] == ["RSI period?"]
    s = c.get(f"/api/strategies/{sid}").json()
    assert s["draft"] is None and len(s["chat"]) == 2


# ---------- agent import ----------

PINE = b"""//@version=5
strategy("RSI bot")
r = ta.rsi(close, 14)
if r < 30
    strategy.entry("L", strategy.long)
if r > 70
    strategy.close("L")
"""


def test_import_purple_json_is_exact_and_round_trips(client):
    sid = client.post("/api/strategies", json={}).json()["id"]
    client.put(f"/api/strategies/{sid}/draft", json=GOOD)
    exported = client.get(f"/api/strategies/{sid}/export").json()
    assert exported["format"] == "purple-strategy"
    r = client.post("/api/agents/import", files={"file": ("rsi.json", json.dumps(exported).encode())}).json()
    assert r["mode"] == "exact" and r["proposal"] is None
    doc = r["strategy"]
    assert doc["draft"]["entry"] == exported["strategy"]["entry"]
    assert doc["source"]["filename"] == "rsi.json"


def test_import_code_uses_ai_and_never_applies_draft():
    prov = FakeProvider(json.dumps({"strategy": {**GOOD, "name": "RSI bot"}, "questions": [], "notes": "Translated RSI rules."}))
    c = TestClient(create_app(store=Store(":memory:"), provider=prov))
    r = c.post("/api/agents/import", files={"file": ("bot.pine", PINE)}).json()
    assert r["mode"] == "ai" and r["proposal"]["strategy"]["name"] == "RSI bot"
    assert r["strategy"]["draft"] is None                     # user must press Apply
    assert r["strategy"]["source"]["content"].startswith("//@version=5")
    prompt = prov.calls[0][-1]["content"]
    assert "never run" in prompt and "ta.rsi(close, 14)" in prompt


def test_import_rejects_binary_bad_type_and_bad_json(client):
    assert client.post("/api/agents/import", files={"file": ("x.py", b"\x00\x01binary")}).status_code == 422
    assert client.post("/api/agents/import", files={"file": ("x.exe", b"MZ text")}).status_code == 422
    # A JSON that is not a Purple strategy now goes to the AI instead (see test_upload_and_ta.py).


def test_import_code_when_ai_offline_returns_503():
    class Offline(FakeProvider):
        def status(self):
            return {"provider": "x", "model": "x", "available": False, "detail": "off"}
    c = TestClient(create_app(store=Store(":memory:"), provider=Offline()))
    assert c.post("/api/agents/import", files={"file": ("bot.py", b"buy if rsi<30")}).status_code == 503


def test_code_percent_check_flags_misread_take_profit():
    from purple_api.ai import code_percent_checks
    code = "strategy.exit(profit = close * 0.05, loss = close * 0.02)\n// trail after 0.03"
    exit_ = {"kind": "any", "items": [
        {"kind": "compare", "left": {"kind": "position", "field": "pnl_pct"}, "op": ">=", "right": {"kind": "const", "value": 3}},
        {"kind": "compare", "left": {"kind": "position", "field": "pnl_pct"}, "op": "<=", "right": {"kind": "const", "value": -2}}]}
    s = Strategy.model_validate({**GOOD, "exit": exit_})
    warn = code_percent_checks(code, s)
    assert len(warn) == 1 and "5%" in warn[0]


def test_store_survives_concurrent_reads(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from purple_api.store import Store
    db = Store(tmp_path / "t.sqlite3")
    ids = [db.create_strategy(f"s{i}")["id"] for i in range(8)]
    with ThreadPoolExecutor(8) as pool:
        out = list(pool.map(lambda k: db.get_strategy(ids[k % 8])["name"], range(400)))
    assert out == [f"s{k % 8}" for k in range(400)]


def test_env_file_loads_without_overriding(tmp_path, monkeypatch):
    from purple_api.envfile import load_env
    f = tmp_path / ".env"
    f.write_text("# comment\nPURPLE_T_A=one\nexport PURPLE_T_B='two'\nPURPLE_T_C=\nPURPLE_T_D=new\n", encoding="utf-8")
    for k in ("PURPLE_T_A", "PURPLE_T_B", "PURPLE_T_C"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PURPLE_T_D", "kept")
    assert load_env(f) == ["PURPLE_T_A", "PURPLE_T_B"]
    import os
    assert os.environ["PURPLE_T_A"] == "one" and os.environ["PURPLE_T_B"] == "two" and os.environ["PURPLE_T_D"] == "kept"
    for k in ("PURPLE_T_A", "PURPLE_T_B"):
        monkeypatch.delenv(k)


def test_provider_choice_and_gemini_request(monkeypatch):
    import httpx
    from purple_api.ai import providers as pv
    monkeypatch.delenv("PURPLE_AI_PROVIDER", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert isinstance(pv.default_provider(), pv.OllamaProvider)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    assert isinstance(pv.default_provider(), pv.GeminiProvider)
    monkeypatch.setenv("PURPLE_AI_PROVIDER", "ollama")
    assert isinstance(pv.default_provider(), pv.OllamaProvider)

    seen = {}
    def fake_post(url, json, timeout, headers):
        seen.update(url=url, body=json, headers=headers)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]})
    monkeypatch.setattr(pv.httpx, "post", fake_post)
    g = pv.GeminiProvider(model="gemini-x", api_key="k1")
    out = g.complete("SYS", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}])
    assert out == '{"ok": true}' and seen["headers"] == {"x-goog-api-key": "k1"} and "k1" not in seen["url"]
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert [c["role"] for c in seen["body"]["contents"]] == ["user", "model"]
    assert g.status()["available"] and not pv.GeminiProvider(api_key="").status()["available"]


def test_gemini_retries_then_falls_back(monkeypatch):
    import httpx
    from purple_api.ai import providers as pv
    urls = []
    def fake_post(url, json, timeout, headers):
        urls.append(url)
        if "main-model" in url:
            return httpx.Response(503, json={"error": {"code": 503}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
    monkeypatch.setattr(pv.httpx, "post", fake_post)
    g = pv.GeminiProvider(model="main-model", api_key="k", fallback="spare-model", retry_wait=0)
    assert g.complete("s", [{"role": "user", "content": "x"}]) == "{}"
    assert [("main" if "main-model" in u else "spare") for u in urls] == ["main", "main", "spare"]


def test_agents_route_with_gemini_drafting():
    from fastapi.testclient import TestClient
    from purple_api.main import create_app
    from purple_api.store import Store

    class FakeGemini:
        name, model = "gemini", "gemini-x"
        def status(self):
            return {"provider": "gemini", "model": "gemini-x", "available": True, "detail": "test"}

    c = TestClient(create_app(store=Store(":memory:"), provider=FakeGemini()))
    r = c.get("/api/superagent/agents")
    assert r.status_code == 200, r.text


def test_browser_connected_ai_is_used_per_request(monkeypatch):
    import httpx
    from fastapi.testclient import TestClient
    from purple_api.ai import providers as pv
    from purple_api.main import create_app
    from purple_api.store import Store

    class Offline:
        name, model = "ollama", "none"
        def status(self):
            return {"provider": "ollama", "model": "none", "available": False, "detail": "offline"}
        def complete(self, system, messages):
            raise AssertionError("server default must not be used when the browser sends a provider")

    calls = []
    def fake_post(url, json, headers, timeout):
        calls.append((url, headers))
        rule = {"name": "x", "entry": {"kind": "compare", "left": {"kind": "indicator", "name": "rsi", "period": 14, "source": "close", "offset": 0},
                                       "op": "<", "right": {"kind": "const", "value": 30}},
                "exit": {"kind": "compare", "left": {"kind": "position", "field": "pnl_pct"}, "op": "<=", "right": {"kind": "const", "value": -5}},
                "questions": []}
        import json as j
        return httpx.Response(200, json={"choices": [{"message": {"content": j.dumps({"strategy": rule, "questions": [], "notes": "ok"})}}]})
    monkeypatch.setattr(pv.httpx, "post", fake_post)
    monkeypatch.setattr(pv.httpx, "get", lambda url, headers, timeout: httpx.Response(200, json={"data": [{"id": "m2"}, {"id": "m1"}]}))

    c = TestClient(create_app(store=Store(":memory:"), provider=Offline()))
    h = {"X-AI-Provider": "groq", "X-AI-Key": "gsk-test", "X-AI-Model": "m1"}
    assert c.get("/api/health").json()["ai"]["available"] is False
    assert c.get("/api/health", headers=h).json()["ai"] == {"provider": "groq", "model": "m1", "available": True, "detail": "groq key from this browser."}
    assert c.post("/api/ai/test", json={"provider": "groq", "key": "gsk-test"}).json() == {"ok": True, "models": ["m1", "m2"]}
    assert c.post("/api/ai/test", json={"provider": "nope", "key": "x"}).status_code == 400
    sid = c.post("/api/strategies", json={"name": "t"}).json()["id"]
    r = c.post(f"/api/strategies/{sid}/ai", json={"message": "rsi under 30"}, headers=h)
    assert r.status_code == 200, r.text
    assert calls and calls[0][0] == "https://api.groq.com/openai/v1/chat/completions" and calls[0][1]["Authorization"] == "Bearer gsk-test"
    engines = {e["id"]: e for e in next(a for a in c.get("/api/superagent/agents", headers={"X-AI-Provider": "gemini", "X-AI-Key": "g"}).json()
                                         if a["kind"] == "ta-original")["engines"]}
    assert engines["gemini-flash"]["available"]
