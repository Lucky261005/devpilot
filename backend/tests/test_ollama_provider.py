"""OllamaProvider against a mocked HTTP transport. No Ollama install is needed."""

import json
import os

import httpx
import pytest

from app.ai.context import SYSTEM_PROMPT
from app.ai.provider import OllamaProvider, get_provider
from app.ai.schema import AIReview
from app.core.db import SessionLocal
from app.workers.queue import run_once

OK_REVIEW = {"summary": "fine", "findings": [], "test_suggestions": []}


def _reply(content, *, done_reason="stop", prompt=120, completion=30):
    body = {
        "model": "m",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": done_reason,
    }
    if prompt is not None:
        body |= {"prompt_eval_count": prompt, "eval_count": completion}
    return httpx.Response(200, json=body)


def _provider(settings, responses, **overrides):
    s = settings.model_copy(update={"llm_provider": "ollama", **overrides})
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request):
        requests.append(request)
        r = responses[len(requests) - 1]
        if isinstance(r, Exception):
            raise r
        return r

    return OllamaProvider(s, transport=httpx.MockTransport(handler)), requests


def test_selected_by_setting_and_reports_local(settings):
    s = settings.model_copy(update={"llm_provider": "ollama"})
    assert s.llm_configured and s.llm_is_local and s.active_llm_model == "qwen2.5-coder:3b"
    p = get_provider(s)
    assert isinstance(p, OllamaProvider) and p.url == "http://127.0.0.1:11434"
    remote = s.model_copy(update={"ollama_url": "http://10.0.0.5:11434"})
    assert not remote.llm_is_local  # only loopback counts as "code stays on this machine"


def test_request_shape(settings):
    p, reqs = _provider(settings, [_reply(json.dumps(OK_REVIEW))])
    p.review("SYS", "USER")
    req = reqs[0]
    body = json.loads(req.content)
    assert req.method == "POST" and req.url.path == "/api/chat"
    assert body["model"] == "qwen2.5-coder:3b" and body["stream"] is False
    assert body["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]
    assert body["format"] == AIReview.model_json_schema()
    assert body["options"] == {"temperature": 0, "num_ctx": settings.ollama_num_ctx}


def test_valid_response_and_token_counts(settings):
    p, _ = _provider(settings, [_reply(json.dumps(OK_REVIEW))])
    r = p.review("s", "u")
    assert r.error is None and r.review == AIReview.model_validate(OK_REVIEW)
    assert (r.input_tokens, r.output_tokens, r.attempts, r.model) == (120, 30, 1, "qwen2.5-coder:3b")


def test_missing_token_counts_are_none(settings):
    p, _ = _provider(settings, [_reply(json.dumps(OK_REVIEW), prompt=None)])
    r = p.review("s", "u")
    assert r.review is not None and r.input_tokens is None and r.output_tokens is None


def test_invalid_output_retried_once_then_fails(settings):
    p, reqs = _provider(settings, [_reply("not json"), _reply(json.dumps(OK_REVIEW))])
    r = p.review("s", "u")
    assert r.review is not None and r.attempts == 2 and len(reqs) == 2
    assert r.input_tokens == 240  # usage summed across attempts

    p, reqs = _provider(settings, [_reply('{"summary": 1}'), _reply("still not json")])
    r = p.review("s", "u")
    assert r.review is None and "schema validation" in r.error and len(reqs) == 2


def test_truncated_output_retried(settings):
    p, _ = _provider(settings, [_reply('{"summ', done_reason="length"), _reply('{"su', done_reason="length")])
    assert "truncated" in p.review("s", "u").error


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.ConnectError("refused"), "not reachable at http://127.0.0.1:11434"),
        (httpx.ReadTimeout("slow"), "timed out"),
        (httpx.Response(404, json={"error": "model 'qwen2.5-coder:3b' not found"}), "ollama pull qwen2.5-coder:3b"),
        (httpx.Response(500, json={"error": "boom"}), "provider error 500"),
    ],
)
def test_transport_failures_are_not_retried(settings, response, expected):
    p, reqs = _provider(settings, [response, response])
    r = p.review("s", "u")
    assert r.review is None and expected in r.error and len(reqs) == 1


def test_prompt_larger_than_context_is_refused_without_calling(settings):
    p, reqs = _provider(settings, [], ollama_num_ctx=100)
    r = p.review("s", "x" * 1000)
    assert r.review is None and "num_ctx" in r.error and reqs == []


def test_review_completes_with_static_findings_when_ollama_down(client, sample_zip, settings):
    from tests.test_api import _import_sample

    rid = _import_sample(client, sample_zip)["id"]
    client.patch(f"/api/repositories/{rid}", json={"ai_review_allowed": True})
    review_id = client.post(f"/api/repositories/{rid}/reviews", json={"kind": "full", "use_ai": True}).json()["id"]

    def down(request):
        raise httpx.ConnectError("refused")

    s = settings.model_copy(update={"llm_provider": "ollama"})
    assert run_once(
        SessionLocal, s, provider_factory=lambda st: OllamaProvider(st, transport=httpx.MockTransport(down))
    )
    review = client.get(f"/api/reviews/{review_id}").json()
    assert review["status"] == "completed"
    assert review["stats"]["ai"]["status"] == "failed" and "not reachable" in review["stats"]["ai"]["reason"]
    rules = {f["rule_id"] for f in client.get(f"/api/reviews/{review_id}/findings").json()}
    assert {"E722", "B602"} <= rules


@pytest.mark.live_llm
@pytest.mark.skipif(not os.environ.get("DEVPILOT_LIVE_OLLAMA"), reason="set DEVPILOT_LIVE_OLLAMA=1 with Ollama running")
def test_live_ollama_returns_valid_review(settings):
    s = settings.model_copy(update={"llm_provider": "ollama"})
    user = (
        "Review: demo\n<repository_content>\nFILE a.py\n(lines 1-2)\n+    1 | def f(xs):\n"
        "+    2 |     return xs[len(xs)]\n</repository_content>"
    )
    r = OllamaProvider(s).review(SYSTEM_PROMPT, user)
    assert r.error is None and r.review is not None


def test_context_budget_fits_the_ollama_window():
    from app.core.config import Settings

    s = Settings(llm_provider="ollama", ollama_num_ctx=16384, llm_max_context_chars=60_000)
    assert s.context_chars == 31_008  # 16384 * 0.75 * 3.5 - 12000: never above what Ollama accepts
    assert Settings(llm_provider="ollama", ollama_num_ctx=32768, llm_max_context_chars=60_000).context_chars == 60_000
    assert Settings(llm_provider="anthropic", llm_max_context_chars=60_000).context_chars == 60_000
