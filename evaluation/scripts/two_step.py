"""Experimental two-step review strategy (benchmark only; never used by the application).

Step A asks the model for plain-text analysis of the same user prompt the pipeline builds.
Step B is the normal structured call (production system prompt, AIReview schema, same retry and
validation rules) with the step-A notes appended as unverified hints. It plugs into the pipeline
through `process_job(..., provider_factory=...)`, so no application code changes.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
from app.ai.provider import LLMResult, OllamaProvider
from app.core.config import Settings

ANALYSIS_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "two_step_analysis.txt").read_text(
    encoding="utf-8"
)
NOTES_TAG = "analysis_notes"
ANALYSIS_MAX_TOKENS = 1024  # bounds step-A latency; notes are hints, not the answer

STEP_B_SUFFIX = f"""

<{NOTES_TAG}>
{{notes}}
</{NOTES_TAG}>

The notes above were written by a previous reading of this same code. They may be wrong. Report a
finding only when the code shown confirms it: cite the exact lines, copy the code as evidence, and
state the triggering input and what goes wrong in the description. Ignore notes you cannot confirm.
Returning zero findings is correct if nothing is confirmed."""


class TwoStepOllamaProvider:
    name = "ollama-two-step"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.inner = OllamaProvider(settings, transport=transport)
        self.model = self.inner.model

    def _analyze(self, user: str) -> tuple[str | None, int, int, str | None]:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": ANALYSIS_PROMPT}, {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": 0, "num_ctx": self.inner.num_ctx, "num_predict": ANALYSIS_MAX_TOKENS},
        }
        try:
            r = self.inner.http.post("/api/chat", json=body)
        except httpx.TimeoutException:
            return None, 0, 0, "timed out"
        except httpx.TransportError:
            return None, 0, 0, f"not reachable at {self.inner.url}"
        if r.status_code >= 400:
            return None, 0, 0, f"HTTP {r.status_code}"
        data = r.json()
        notes = ((data.get("message") or {}).get("content") or "").strip()
        tin, tout = data.get("prompt_eval_count") or 0, data.get("eval_count") or 0
        if not notes:
            return None, tin, tout, "empty analysis"
        return notes, tin, tout, None

    def review(self, system: str, user: str) -> LLMResult:
        started = time.monotonic()
        notes, a_in, a_out, err = self._analyze(user)
        if err:
            return LLMResult(
                None,
                self.model,
                int((time.monotonic() - started) * 1000),
                a_in or None,
                a_out or None,
                attempts=1,
                error=f"analysis step failed: {err}",
            )
        # The notes are model output derived from untrusted code: fence them like repository content.
        safe = notes.replace(f"<{NOTES_TAG}", f"<​{NOTES_TAG}").replace(f"</{NOTES_TAG}", f"<​/{NOTES_TAG}")
        result = self.inner.review(system, user + STEP_B_SUFFIX.format(notes=safe))
        result.latency_ms = int((time.monotonic() - started) * 1000)
        result.input_tokens = (result.input_tokens or 0) + a_in or None
        result.output_tokens = (result.output_tokens or 0) + a_out or None
        result.attempts += 1  # step A counts as one call
        return result
