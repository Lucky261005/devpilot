"""LLM provider abstraction. The review pipeline depends only on `LLMProvider`."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from app.ai.schema import AIReview
from app.core.config import Settings

log = logging.getLogger(__name__)


@dataclass
class LLMResult:
    review: Any  # an instance of the requested schema (AIReview unless the caller asked otherwise)
    model: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    attempts: int = 1
    error: str | None = None  # set when no valid review was produced


class LLMProvider(Protocol):
    name: str
    model: str

    def review(self, system: str, user: str, schema: type[BaseModel] = AIReview) -> LLMResult: ...


class ProviderUnavailable(RuntimeError):
    pass


class AnthropicProvider:
    """Claude via the official SDK, using structured outputs parsed into `AIReview`."""

    name = "anthropic"

    def __init__(self, settings: Settings):
        import anthropic

        self._anthropic = anthropic
        self.model = settings.llm_model
        self.effort = settings.llm_effort
        # The SDK retries 408/409/429/5xx and connection errors with backoff.
        self.client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_s, max_retries=2
        )

    def review(self, system: str, user: str, schema: type[BaseModel] = AIReview) -> LLMResult:
        a = self._anthropic
        started = time.monotonic()
        attempts = 0
        in_tok = out_tok = 0
        last_error = "unknown error"
        # One extra attempt if the model returns output that fails schema validation.
        for attempts in range(1, 3):  # noqa: B007
            try:
                resp = self.client.messages.parse(
                    model=self.model,
                    max_tokens=16000,
                    system=system,
                    output_config={"effort": self.effort},  # type: ignore[arg-type]
                    messages=[{"role": "user", "content": user}],
                    output_format=schema,
                )
            except (a.AuthenticationError, a.PermissionDeniedError) as e:
                last_error = f"provider rejected credentials ({type(e).__name__})"
                break
            except a.BadRequestError as e:
                last_error = f"provider rejected request: {e.message[:300]}"
                break
            except (a.RateLimitError, a.APIConnectionError, a.APITimeoutError) as e:
                last_error = f"provider unavailable ({type(e).__name__})"
                break  # SDK already retried with backoff
            except a.APIStatusError as e:
                last_error = f"provider error {e.status_code}"
                break
            except ValidationError as e:
                last_error = f"output failed schema validation: {e.error_count()} errors"
                continue
            in_tok += resp.usage.input_tokens
            out_tok += resp.usage.output_tokens
            if resp.stop_reason == "refusal":
                last_error = "model declined the request"
                break
            if resp.stop_reason == "max_tokens":
                last_error = "output truncated at max_tokens"
                continue
            if resp.parsed_output is None:
                last_error = "model returned no structured output"
                continue
            return LLMResult(
                review=resp.parsed_output,
                model=self.model,
                latency_ms=int((time.monotonic() - started) * 1000),
                input_tokens=in_tok,
                output_tokens=out_tok,
                attempts=attempts,
            )
        log.warning("llm review failed: %s", last_error)
        return LLMResult(
            review=None,
            model=self.model,
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=in_tok or None,
            output_tokens=out_tok or None,
            attempts=attempts,
            error=last_error,
        )


class OllamaProvider:
    """A local model served by Ollama (`POST /api/chat`), constrained to the `AIReview` JSON schema.

    Failure semantics match `AnthropicProvider`: one retry when the output fails schema
    validation or is truncated; no retry for transport errors (a local server that refused or
    timed out once will do the same again, and a retried timeout doubles the wait)."""

    name = "ollama"
    CHARS_PER_TOKEN = 3.5  # rough estimate for code; only used to refuse prompts that can't fit

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.model = settings.ollama_model
        self.url = settings.ollama_url
        self.num_ctx = settings.ollama_num_ctx
        self.http = httpx.Client(base_url=self.url, timeout=settings.llm_timeout_s, transport=transport)

    def review(self, system: str, user: str, schema: type[BaseModel] = AIReview) -> LLMResult:
        started = time.monotonic()
        attempts = 0
        in_tok = out_tok = 0
        last_error = "unknown error"
        # Ollama silently drops the start of prompts longer than num_ctx; refuse instead.
        if (len(system) + len(user)) / self.CHARS_PER_TOKEN > self.num_ctx * 0.75:
            return LLMResult(
                None,
                self.model,
                0,
                error=f"prompt too large for num_ctx={self.num_ctx}; lower DEVPILOT_LLM_MAX_CONTEXT_CHARS "
                "or raise DEVPILOT_OLLAMA_NUM_CTX",
            )
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema.model_json_schema(),
            "stream": False,
            "options": {"temperature": 0, "num_ctx": self.num_ctx},
        }
        for attempts in range(1, 3):  # noqa: B007
            try:
                r = self.http.post("/api/chat", json=body)
            except httpx.TimeoutException:
                last_error = f"Ollama timed out after {self.http.timeout.read}s"
                break
            except httpx.TransportError:
                last_error = f"Ollama is not reachable at {self.url} (is `ollama serve` running?)"
                break
            if r.status_code == 404:
                last_error = f"model '{self.model}' is not available in Ollama; run `ollama pull {self.model}`"
                break
            if r.status_code >= 400:
                last_error = f"provider error {r.status_code}"
                break
            data = r.json()
            in_tok += data.get("prompt_eval_count") or 0
            out_tok += data.get("eval_count") or 0
            if data.get("done_reason") == "length":
                last_error = "output truncated at the model's length limit"
                continue
            try:
                review = schema.model_validate_json((data.get("message") or {}).get("content") or "")
            except ValidationError as e:
                last_error = f"output failed schema validation: {e.error_count()} errors"
                continue
            return LLMResult(
                review=review,
                model=self.model,
                latency_ms=int((time.monotonic() - started) * 1000),
                input_tokens=in_tok or None,
                output_tokens=out_tok or None,
                attempts=attempts,
            )
        log.warning("llm review failed: %s", last_error)
        return LLMResult(
            review=None,
            model=self.model,
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=in_tok or None,
            output_tokens=out_tok or None,
            attempts=attempts,
            error=last_error,
        )


class StaticReplayProvider:
    """Returns a fixed response. Used by tests and the evaluation harness's replay mode;
    never selected by the application at runtime."""

    name = "replay"

    def __init__(self, payload: dict | str | Exception, model: str = "replay"):
        self.payload = payload
        self.model = model
        self.calls: list[tuple[str, str]] = []

    def review(self, system: str, user: str, schema: type[BaseModel] = AIReview) -> LLMResult:
        self.calls.append((system, user))
        if isinstance(self.payload, Exception):
            return LLMResult(None, self.model, 0, error=str(self.payload))
        try:
            data = (
                schema.model_validate_json(self.payload)
                if isinstance(self.payload, str)
                else schema.model_validate(self.payload)
            )
        except ValidationError as e:
            return LLMResult(None, self.model, 0, error=f"output failed schema validation: {e.error_count()} errors")
        return LLMResult(data, self.model, 0, input_tokens=len(user) // 4, output_tokens=100)


def get_provider(settings: Settings) -> LLMProvider:
    if not settings.llm_configured:
        raise ProviderUnavailable(
            "No LLM provider is configured. Set DEVPILOT_LLM_PROVIDER=ollama for a local model, "
            "or ANTHROPIC_API_KEY for Claude."
        )
    if settings.llm_provider == "ollama":
        return OllamaProvider(settings)
    return AnthropicProvider(settings)
