import io
import json
import time
import zipfile
import zlib

import pytest
from fastapi.testclient import TestClient

from purple_api import agents, superagent as sa
from purple_api.main import create_app
from purple_api.sample import synthetic_bars
from purple_api.store import Store

from test_superagent import TeamProvider, wait


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, s in files.items():
            z.writestr(n, s)
    return buf.getvalue()


def test_xlsx_cells_read_with_shared_strings():
    data = _zip({
        "xl/sharedStrings.xml": '<sst xmlns="x"><si><t>Buy when</t></si><si><t>RSI(14) &lt; 30</t></si></sst>',
        "xl/worksheets/sheet1.xml": '<worksheet xmlns="x"><sheetData><row><c t="s"><v>0</v></c><c t="s"><v>1</v></c>'
                                    '<c><v>5</v></c></row></sheetData></worksheet>',
    })
    kind, text = agents.decode_upload("plan.xlsx", data)
    assert kind == "document" and "Buy when\tRSI(14) < 30\t5" in text


def test_docx_paragraphs_read():
    data = _zip({"word/document.xml": '<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>Sell when RSI</w:t></w:r>'
                                      '<w:r><w:t> &gt; 70</w:t></w:r></w:p></w:body></w:document>'})
    assert agents.decode_upload("s.docx", data) == ("document", "Sell when RSI > 70")


def test_pdf_simple_text_read():
    content = b"BT /F1 12 Tf 72 700 Td (Buy when the close crosses above SMA 50.) Tj T* [(Sell) -300 (on a 5% loss.)] TJ ET"
    stream = zlib.compress(content)
    pdf = (b"%PDF-1.4\n1 0 obj << /Length " + str(len(stream)).encode() + b" /Filter /FlateDecode >>\nstream\n"
           + stream + b"\nendstream\nendobj\n%%EOF")
    kind, text = agents.decode_upload("idea.pdf", pdf)
    assert kind == "document" and "crosses above SMA 50." in text and "Sell on a 5% loss." in text


def test_unreadable_pdf_and_old_formats_explain():
    with pytest.raises(agents.AgentError, match="PDF"):
        agents.decode_upload("scan.pdf", b"%PDF-1.4\n%%EOF")
    with pytest.raises(agents.AgentError, match=".xlsx"):
        agents.decode_upload("old.xls", b"\xd0\xcf\x11\xe0")


def test_price_csv_is_redirected():
    with pytest.raises(agents.AgentError, match="price data"):
        agents.decode_upload("infy.csv", b"Date,Open,High,Low,Close\n2025-01-01,1,2,0.5,1.5\n")


def test_non_purple_json_goes_to_ai_and_nothing_runs():
    reply = json.dumps({"strategy": None, "questions": ["No strategy found in the file."], "notes": ""})

    class P(TeamProvider):
        def complete(self, system, messages):
            return reply
    c = TestClient(create_app(store=Store(":memory:"), provider=P()))
    r = c.post("/api/agents/import", files={"file": ("config.json", b'{"api": "x", "symbols": ["INFY"]}', "application/json")})
    assert r.status_code == 200 and r.json()["mode"] == "ai"
    assert r.json()["strategy"]["source"]["kind"] == "document"


def test_superagent_has_no_user_agents():
    c = TestClient(create_app(store=Store(":memory:"), provider=TeamProvider()))
    ds = c.get("/api/datasets").json()[0]
    r = c.post("/api/superagent/run", json={"agent_id": "strategy:abc", "dataset_id": ds["id"]})
    assert r.status_code == 404


def test_original_tradingagents_bridge(monkeypatch):
    """The real TradingAgents runs in its own process; here that process is faked."""
    bars = synthetic_bars(300)
    calls = []

    def fake_process(args, on_event, timeout_s, extra_env=None):
        if "--prices" in args:
            return {"event": "prices", "bars": [[b.date, b.open, b.high, b.low, b.close, b.volume] for b in bars]}
        calls.append(args)
        on_event({"event": "step", "who": "market_report", "text": "Market analyst finished."})
        rating = ["Buy", "Overweight", "Sell"][len(calls) - 1]
        return {"event": "result", "rating": rating, "action": {"Buy": "BUY", "Overweight": "BUY", "Sell": "SELL"}[rating],
                "reports": {"final_trade_decision": f"Rating: {rating}"}, "bull": "b", "bear": "r"}

    monkeypatch.setattr(sa, "_ta_process", fake_process)
    monkeypatch.setattr(sa, "ta_installed", lambda: True)
    c = TestClient(create_app(store=Store(":memory:"), provider=TeamProvider()))
    r = c.post("/api/superagent/run", json={"agent_id": "tradingagents-original", "symbol": "reliance", "days": 3,
                                             "analyses": ["market", "news"]})
    assert r.status_code == 200, r.text
    j = wait(c, r.json()["job"]["id"])
    assert j["status"] == "done", j["error"]
    acts = [d["action"] for d in j["result"]["decisions"]]
    assert acts == ["BUY", "HOLD", "SELL"]  # Overweight while holding -> keep
    assert calls[0][calls[0].index("--ticker") + 1] == "RELIANCE.NS"
    assert calls[0][calls[0].index("--analysts") + 1] == "market,news"
    assert any(l["kind"] == "market_report" for l in j["log"])
    assert j["result"]["dataset"]["symbol"] == "RELIANCE.NS"
    out = c.get("/api/superagent/export", params={"agent_id": "tradingagents-original", "symbol": "RELIANCE"}).json()
    compile(out["code"], "ta.py", "exec")
    assert "RELIANCE.NS" in out["code"] and "DRY_RUN = True" in out["code"]


def test_ta_cloud_engine_choice(monkeypatch):
    """Cloud engines: key must be set, paid ones need explicit confirmation, runner gets the cloud models."""
    bars = synthetic_bars(300)
    calls = []

    def fake_process(args, on_event, timeout_s, extra_env=None):
        if "--prices" in args:
            return {"event": "prices", "bars": [[b.date, b.open, b.high, b.low, b.close, b.volume] for b in bars]}
        calls.append(args)
        return {"event": "result", "rating": "Hold", "action": "HOLD", "reports": {}, "bull": "", "bear": "",
                "usage": {"calls": 18, "input_tokens": 60000, "output_tokens": 9000}}

    monkeypatch.setattr(sa, "_ta_process", fake_process)
    monkeypatch.setattr(sa, "ta_installed", lambda: True)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    c = TestClient(create_app(store=Store(":memory:"), provider=TeamProvider()))
    body = {"agent_id": "tradingagents-original", "symbol": "TCS", "days": 1, "analyses": ["market"]}

    engines = {e["id"]: e for e in next(a for a in c.get("/api/superagent/agents").json()
                                        if a["id"] == "tradingagents-original")["engines"]}
    assert engines["local"]["available"] and not engines["claude-opus"]["available"]
    assert "ANTHROPIC_API_KEY" in engines["claude-opus"]["why"]
    assert c.post("/api/superagent/run", json=body | {"engine": "claude-opus", "confirm_paid": True}).status_code == 503
    assert c.post("/api/superagent/run", json=body | {"engine": "nope"}).status_code == 422

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    assert c.post("/api/superagent/run", json=body | {"engine": "claude-opus"}).status_code == 402  # not confirmed
    r = c.post("/api/superagent/run", json=body | {"engine": "claude-opus", "confirm_paid": True})
    assert r.status_code == 200, r.text
    j = wait(c, r.json()["job"]["id"])
    assert j["status"] == "done", j["error"]
    args = calls[-1]
    assert args[args.index("--provider") + 1] == "anthropic" and args[args.index("--deep") + 1] == "claude-opus-5-5"
    assert "--model" not in args
    assert any("18 calls" in n for n in j["result"]["decisions"][0]["notes"])


def test_ta_process_passes_only_the_chosen_key(monkeypatch):
    seen = {}

    class FakeProc:
        def __init__(self):
            self.stdout = iter(['{"event": "result", "rating": "Hold"}\n'])

        def wait(self):
            return 0

        def kill(self):
            pass

    def fake_popen(cmd, **kw):
        seen.update(kw["env"])
        return FakeProc()

    monkeypatch.setattr(sa.subprocess, "Popen", fake_popen)
    for k, v in {"ANTHROPIC_API_KEY": "a", "GOOGLE_API_KEY": "g", "OPENAI_API_KEY": "o"}.items():
        monkeypatch.setenv(k, v)
    sa._ta_process(["--ticker", "X.NS", "--provider", "google"], lambda e: None, 5)
    assert seen.get("GOOGLE_API_KEY") == "g" and "ANTHROPIC_API_KEY" not in seen and "OPENAI_API_KEY" not in seen
    seen.clear()
    sa._ta_process(["--ticker", "X.NS", "--provider", "ollama"], lambda e: None, 5)
    assert not [k for k in seen if k.endswith("_API_KEY")]
