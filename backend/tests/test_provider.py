"""AnthropicProvider behaviour with the SDK client replaced by a fake (no network)."""

import os
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from pydantic import ValidationError

from app.ai.context import SYSTEM_PROMPT
from app.ai.provider import AnthropicProvider, ProviderUnavailable, get_provider
from app.ai.schema import AIReview

OK = AIReview(summary="fine", findings=[], test_suggestions=[])


def _resp(parsed=OK, stop="end_turn"):
    return SimpleNamespace(
        parsed_output=parsed, stop_reason=stop, usage=SimpleNamespace(input_tokens=100, output_tokens=20)
    )


def _provider(settings, behaviours):
    p = AnthropicProvider(settings.model_copy(update={"anthropic_api_key": "sk-ant-test"}))
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        b = behaviours[len(calls) - 1]
        if isinstance(b, Exception):
            raise b
        return b

    p.client = SimpleNamespace(messages=SimpleNamespace(parse=parse))
    return p, calls


def _validation_error():
    try:
        AIReview.model_validate({"summary": 1})
    except ValidationError as e:
        return e


def _status_error(cls, code):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("err", response=httpx.Response(code, request=req), body=None)


def test_success_records_usage_and_sends_structured_request(settings):
    p, calls = _provider(settings, [_resp()])
    r = p.review("sys", "user")
    assert r.review == OK and r.error is None and r.input_tokens == 100 and r.attempts == 1
    assert calls[0]["output_format"] is AIReview and calls[0]["model"] == settings.llm_model
    assert calls[0]["system"] == "sys" and calls[0]["output_config"] == {"effort": settings.llm_effort}


def test_retries_once_on_schema_violation(settings):
    p, calls = _provider(settings, [_validation_error(), _resp()])
    r = p.review("s", "u")
    assert r.review == OK and r.attempts == 2 and len(calls) == 2


def test_gives_up_after_two_invalid_outputs(settings):
    p, _ = _provider(settings, [_validation_error(), _validation_error()])
    r = p.review("s", "u")
    assert r.review is None and "schema validation" in r.error


def test_auth_error_is_not_retried_and_message_has_no_key(settings):
    p, calls = _provider(settings, [_status_error(anthropic.AuthenticationError, 401)])
    r = p.review("s", "u")
    assert len(calls) == 1 and "credentials" in r.error and "sk-ant" not in r.error


def test_refusal_and_truncation_are_failures(settings):
    p, _ = _provider(settings, [_resp(stop="refusal")])
    assert p.review("s", "u").error == "model declined the request"
    p, _ = _provider(settings, [_resp(parsed=None, stop="max_tokens"), _resp(parsed=None, stop="max_tokens")])
    assert "truncated" in p.review("s", "u").error


def test_rate_limit_reports_unavailable(settings):
    p, _ = _provider(settings, [_status_error(anthropic.RateLimitError, 429)])
    assert "unavailable" in p.review("s", "u").error


def test_get_provider_without_key(settings):
    with pytest.raises(ProviderUnavailable):
        get_provider(settings.model_copy(update={"anthropic_api_key": ""}))


@pytest.mark.live_llm
@pytest.mark.skipif(not os.environ.get("DEVPILOT_LIVE_ANTHROPIC_KEY"), reason="needs a real key")
def test_live_anthropic_returns_valid_review(settings):
    s = settings.model_copy(update={"anthropic_api_key": os.environ["DEVPILOT_LIVE_ANTHROPIC_KEY"]})
    user = (
        "Review: demo\n<repository_content>\nFILE a.py\n(lines 1-2)\n+    1 | def f(xs):\n"
        "+    2 |     return xs[len(xs)]\n</repository_content>"
    )
    r = AnthropicProvider(s).review(SYSTEM_PROMPT, user)
    assert r.error is None and r.review is not None
