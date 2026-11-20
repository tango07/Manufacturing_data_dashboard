"""Tests for the chat assistant, the server, and the dashboard."""

from __future__ import annotations

import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlreq

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from api import chat as chat_service  # noqa: E402
from api.assistant_core import (MissingApiKey, MissingModel, ProviderError, build_chat_request,  # noqa: E402
                                data_context, get_api_key, get_model, normalize_messages, pre_check,
                                summary_for_llm)
from api.server import build_server, load_dotenv  # noqa: E402

PAYLOAD_PATH = ROOT / "data" / "processed" / "kpis.json"
DASHBOARD_PATH = ROOT / "dashboard" / "index.html"
KEY_ENV = {"LLM_API_KEY": "test-key-123", "LLM_MODEL": "model-x"}


@pytest.fixture(scope="module")
def payload():
    if not PAYLOAD_PATH.exists():
        pytest.skip("run the pipeline first: python -m pipeline.run --input data/raw/full_export")
    return json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))


def q(text):
    return {"messages": [{"role": "user", "content": text}]}


# ---------- key and model handling -------------------------------------------------------------

def test_missing_key_raises_and_names_the_setting():
    with pytest.raises(MissingApiKey) as exc:
        get_api_key(env={})
    assert "LLM_API_KEY" in str(exc.value)


def test_key_read_from_environment_only():
    assert get_api_key(env={"LLM_API_KEY": "test-value"}) == "test-value"


def test_missing_model_is_reported():
    with pytest.raises(MissingModel):
        get_model(env={})


def test_dashboard_bundle_contains_no_key_or_provider_url():
    if not DASHBOARD_PATH.exists():
        pytest.skip("dashboard not built")
    html = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert not re.search(r"sk-[A-Za-z0-9_-]{16,}", html)
    assert "LLM_API_KEY" not in html
    assert "api.anthropic.com" not in html


# ---------- what the model is given -----------------------------------------------------------

def test_context_contains_the_figures_needed_for_any_question(payload):
    ctx = data_context(payload)
    assert set(ctx["plants"]) == set(payload["filters"]["plants"])
    assert set(ctx["shifts"]) == set(payload["filters"]["shifts"])
    assert len(ctx["machines"]) == len(payload["by_machine"]) > 0
    assert ctx["headline"]["K2"]["value"] == payload["blocks"]["ALL|ALL"]["K2"]["value"]
    assert {"Q1", "Q2", "Q3", "Q4", "Q5"} <= set(ctx["leadership"])
    assert ctx["data_quality"] and ctx["assumptions"]


def test_summary_keeps_the_kpi_keys_used_by_grounding(payload):
    s = summary_for_llm(payload)
    assert "K2" in s["kpis"] and s["kpis"]["K2"]["denominator"] is not None


def test_request_caches_the_context_and_carries_history(payload):
    msgs = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "Which machine costs most?"}]
    req = build_chat_request(msgs, payload, model="model-x")
    blocks = req["system"]
    # The system prompt is organised into XML sections.
    for tag in ("role", "rules", "answer_format"):
        assert f"<{tag}>" in blocks[0]["text"] and f"</{tag}>" in blocks[0]["text"]
    assert blocks[0]["text"].count('<rule id="') == 7
    # The data context is a separate cached block.
    assert blocks[1]["cache_control"] == {"type": "ephemeral"}
    assert "<data_context>" in blocks[1]["text"]
    # Each turn is wrapped: questions in <question>, earlier replies in <answer>.
    assert [m["role"] for m in req["messages"]] == ["user", "assistant", "user"]
    assert req["messages"][0]["content"] == "<question>Hi</question>"
    assert req["messages"][1]["content"] == "<answer>Hello</answer>"
    assert req["messages"][2]["content"] == "<question>Which machine costs most?</question>"
    assert "test-key-123" not in json.dumps(req)


def test_normalize_messages_keeps_alternation_and_ends_on_user():
    raw = [{"role": "assistant", "content": "stray"}, {"role": "user", "content": "a"},
           {"role": "user", "content": "a2"}, {"role": "assistant", "content": "b"},
           {"role": "user", "content": "c"}, {"role": "assistant", "content": "   "}]
    out = normalize_messages(raw)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert out[0]["content"] == "a2"
    assert out[-1]["content"] == "c"


def test_normalize_messages_rejects_garbage_and_long_history():
    assert normalize_messages("nope") == []
    assert normalize_messages([{"role": "assistant", "content": "only assistant"}]) == []
    long = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(40)]
    long.append({"role": "user", "content": "last"})
    out = normalize_messages(long)
    assert len(out) <= 12 and out[-1]["content"] == "last" and out[0]["role"] == "user"


def test_plant_that_does_not_exist_is_refused_without_model(payload):
    resp = pre_check("What is the scrap rate for PLT-09?", payload)
    assert resp is not None and resp["status"] == "insufficient_evidence"
    assert "PLT-09" in resp["answer"]


def test_real_plant_is_not_refused(payload):
    assert pre_check("How is PLT-01 doing?", payload) is None


# ---------- chat service -----------------------------------------------------------------------

def test_free_text_without_key_says_not_connected(payload):
    out = chat_service.answer(q("Which supplier is the problem?"), payload, env={})
    assert out["mode"] == "unavailable"
    assert "LLM_API_KEY" in out["answer"]


def test_suggested_question_without_key_uses_pipeline_answer(payload):
    out = chat_service.answer({"question_id": "Q1"}, payload, env={})
    assert out["mode"] == "pipeline"
    assert out["answer"] == payload["leadership"]["Q1"]["answer"]


def test_off_topic_question_now_reaches_the_model(payload):
    calls = []

    def fake(req, key, url):
        calls.append(req)
        return "That is outside this data. I can answer questions about plants and costs."

    out = chat_service.answer(q("What is the weather in Pune?"), payload, KEY_ENV, llm_call=fake)
    assert out["mode"] == "llm" and calls


def test_any_business_question_is_sent_with_its_history(payload):
    seen = {}

    def fake(req, key, url):
        seen["req"] = req
        seen["key"] = key
        return "  MC-07 costs the most.  "

    body = {"messages": [{"role": "user", "content": "Which machine costs most?"},
                         {"role": "assistant", "content": "MC-07."},
                         {"role": "user", "content": "And why?"}]}
    out = chat_service.answer(body, payload, KEY_ENV, llm_call=fake)
    assert out == {"mode": "llm", "answer": "MC-07 costs the most.", "question_id": None}
    assert len(seen["req"]["messages"]) == 3
    assert seen["req"]["model"] == "model-x"
    assert seen["key"] == "test-key-123"


def test_provider_failure_for_free_text_shows_safe_message(payload):
    def boom(*a):
        raise ProviderError("The provider rejected the API key. Check LLM_API_KEY in the .env file.")

    out = chat_service.answer(q("Why is scrap high?"), payload, KEY_ENV, llm_call=boom)
    assert out["mode"] == "error"
    assert "test-key-123" not in json.dumps(out)


def test_provider_failure_for_suggested_question_falls_back(payload):
    def boom(*a):
        raise ProviderError("The model service is unavailable right now.")

    out = chat_service.answer({"question_id": "Q5"}, payload, KEY_ENV, llm_call=boom)
    assert out["mode"] == "pipeline" and out["answer"] == payload["leadership"]["Q5"]["answer"]


def test_overlong_or_empty_input_rejected(payload):
    assert chat_service.answer({"question": "   "}, payload, env={})["mode"] == "error"
    assert chat_service.answer({"messages": []}, payload, env={})["mode"] == "error"


# ---------- streaming --------------------------------------------------------------------------

def test_stream_emits_deltas_then_done(payload):
    def fake_stream(req, key, url):
        yield "Scrap "
        yield "is 3.8%."

    events = list(chat_service.stream(q("How is scrap?"), payload, KEY_ENV, llm_stream=fake_stream))
    assert [e.get("delta") for e in events if "delta" in e] == ["Scrap ", "is 3.8%."]
    assert events[-1] == {"done": True, "mode": "llm", "question_id": None}


def test_stream_error_before_any_text_is_reported(payload):
    def fake_stream(req, key, url):
        raise ProviderError("The model is busy (rate limit). Try again in a moment.")
        yield  # pragma: no cover

    events = list(chat_service.stream(q("How is scrap?"), payload, KEY_ENV, llm_stream=fake_stream))
    assert events == [{"error": "The model is busy (rate limit). Try again in a moment.", "mode": "error"}]


def test_stream_fallback_for_suggested_question(payload):
    def fake_stream(req, key, url):
        raise ProviderError("unavailable")
        yield  # pragma: no cover

    events = list(chat_service.stream({"question_id": "Q3"}, payload, KEY_ENV, llm_stream=fake_stream))
    assert events[0]["delta"] == payload["leadership"]["Q3"]["answer"]
    assert events[-1]["mode"] == "pipeline"


# ---------- server (real HTTP, fake provider) --------------------------------------------------

class _FakeProvider(BaseHTTPRequestHandler):
    received = {}
    status = 200

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        _FakeProvider.received = {"key": self.headers.get("x-api-key"), "model": body.get("model"),
                                  "stream": bool(body.get("stream")), "system": body.get("system")}
        if _FakeProvider.status != 200:
            self.send_response(_FakeProvider.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        if body.get("stream"):
            events = [
                ("message_start", {"type": "message_start"}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "text_delta", "text": "Hello "}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "text_delta", "text": "COO."}}),
                ("message_stop", {"type": "message_stop"}),
            ]
            out = "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        out = json.dumps({"content": [{"type": "text", "text": "Hello COO."}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        return


@pytest.fixture()
def provider():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeProvider)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _FakeProvider.status = 200
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1/messages"
    srv.shutdown()
    srv.server_close()


@pytest.fixture()
def running_server(payload):
    servers = []

    def start(env):
        srv = build_server("127.0.0.1", 0, DASHBOARD_PATH, payload, env)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    yield start
    for s in servers:
        s.shutdown()
        s.server_close()


def _post(url, body):
    req = urlreq.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"},
                         method="POST")
    with urlreq.urlopen(req, timeout=20) as r:
        return r.status, r.headers.get("Content-Type"), r.read().decode()


def _events(text):
    return [json.loads(line[5:]) for line in text.split("\n\n") if line.startswith("data:")]


def test_server_serves_dashboard_and_health(running_server):
    if not DASHBOARD_PATH.exists():
        pytest.skip("dashboard not built")
    base = running_server({})
    with urlreq.urlopen(base + "/", timeout=10) as r:
        html = r.read().decode()
        assert "Ask the assistant" in html
        assert r.headers["X-Content-Type-Options"] == "nosniff"
    with urlreq.urlopen(base + "/api/health", timeout=10) as r:
        assert json.loads(r.read()) == {"status": "ok", "llm_configured": False}


def test_server_chat_without_key_never_exposes_it(running_server):
    base = running_server({"LLM_API_KEY": "sk-should-not-leak", "LLM_MODEL": ""})
    status, _, text = _post(base + "/api/chat/stream", q("Why is scrap high?"))
    assert status == 200
    assert "sk-should-not-leak" not in text
    assert _events(text)[-1]["mode"] == "unavailable"


def test_server_streams_a_real_reply_through_the_provider(running_server, provider):
    base = running_server({"LLM_API_KEY": "test-key-123", "LLM_MODEL": "fake-model", "LLM_BASE_URL": provider})
    status, ctype, text = _post(base + "/api/chat/stream", q("Anything about scrap?"))
    assert status == 200 and ctype.startswith("text/event-stream")
    events = _events(text)
    assert "".join(e.get("delta", "") for e in events) == "Hello COO."
    assert events[-1] == {"done": True, "mode": "llm", "question_id": None}
    assert _FakeProvider.received["key"] == "test-key-123"
    assert _FakeProvider.received["model"] == "fake-model"
    assert _FakeProvider.received["stream"] is True
    assert _FakeProvider.received["system"][1]["cache_control"] == {"type": "ephemeral"}


def test_server_non_streaming_endpoint_still_works(running_server, provider):
    base = running_server({"LLM_API_KEY": "test-key-123", "LLM_MODEL": "fake-model", "LLM_BASE_URL": provider})
    status, _, text = _post(base + "/api/chat", q("Anything about scrap?"))
    assert status == 200 and json.loads(text)["answer"] == "Hello COO."


def test_provider_rejecting_the_key_gives_a_clear_message(running_server, provider):
    _FakeProvider.status = 401
    base = running_server({"LLM_API_KEY": "test-key-123", "LLM_MODEL": "fake-model", "LLM_BASE_URL": provider})
    status, _, text = _post(base + "/api/chat/stream", q("Anything about scrap?"))
    last = _events(text)[-1]
    assert last["mode"] == "error" and "rejected the API key" in last["error"]
    assert "test-key-123" not in text


def test_server_rejects_bad_bodies(running_server):
    base = running_server({})
    req = urlreq.Request(base + "/api/chat/stream", data=b"not json",
                         headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(Exception) as exc:
        urlreq.urlopen(req, timeout=10)
    assert "400" in str(exc.value)


def test_load_dotenv_does_not_override_environment(tmp_path):
    f = tmp_path / ".env"
    f.write_text("LLM_API_KEY=from-file\nLLM_MODEL='m-1'\n# comment\n", encoding="utf-8")
    env = {"LLM_API_KEY": "from-env"}
    load_dotenv(f, env)
    assert env == {"LLM_API_KEY": "from-env", "LLM_MODEL": "m-1"}


# ---------- dashboard --------------------------------------------------------------------------

def test_dashboard_has_no_leadership_section_and_streams_chat():
    html = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "Leadership answers" not in html
    assert 'id="chips"' in html and "/api/chat/stream" in html and 'id="clearChat"' in html


def test_dashboard_embeds_the_pipeline_row_counts(payload):
    html = DASHBOARD_PATH.read_text(encoding="utf-8")
    embedded = json.loads(re.search(r"const DATA = (\{.*?\});\n", html).group(1))
    assert embedded["row_counts"] == payload["row_counts"]


# ---------- connection failures ----------------------------------------------------------------

def test_network_errors_are_classified_with_a_specific_message():
    import socket as _socket
    import ssl as _ssl
    import urllib.error as _ue
    from api.assistant_core import describe_network_error

    cert = _ue.URLError(_ssl.SSLCertVerificationError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"))
    assert "certificate check" in describe_network_error(cert)
    assert "did not respond" in describe_network_error(_ue.URLError(_socket.timeout("timed out")))
    assert "look up" in describe_network_error(_ue.URLError(_socket.gaierror("nodename nor servname")))
    assert "refused" in describe_network_error(_ue.URLError(ConnectionRefusedError(61, "Connection refused")))


def test_unreachable_provider_gives_a_specific_message_and_no_key(payload):
    from api.assistant_core import call_llm
    with pytest.raises(ProviderError) as exc:
        call_llm({"model": "m", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]},
                 "test-key-123", base_url="http://127.0.0.1:1/v1/messages", timeout=5)
    assert "refused" in str(exc.value)
    assert "test-key-123" not in str(exc.value)


def test_streaming_unreachable_provider_is_reported_not_raised(payload):
    from api.assistant_core import stream_llm
    with pytest.raises(ProviderError):
        list(stream_llm({"model": "m", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]},
                        "test-key-123", base_url="http://127.0.0.1:1/v1/messages", timeout=5))
