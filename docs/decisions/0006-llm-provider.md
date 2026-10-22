# ADR 0006: A minimal provider interface with Anthropic as the implementation

**Status:** accepted (2026-10-17)

**Context.** The review must not depend on one vendor, must work without any provider, and must
be testable without network access.

**Options.** Call the SDK directly from the pipeline; a generic multi-vendor library; a small
in-house interface.

**Decision.** An `LLMProvider` protocol with one method, `review(system, user) -> LLMResult`
(a parsed `AIReview` or an error, plus model, latency, tokens and attempts). `AnthropicProvider`
uses the official SDK's `messages.parse` with the Pydantic schema. `get_provider` raises
`ProviderUnavailable` when no key is set, and the pipeline records "skipped". Tests use
`StaticReplayProvider`.

**Benefits.** The pipeline never sees vendor types. Errors are normalized into a reason string the
UI can show. Adding a provider (including a local model) is one new class.

**Costs.** Vendor features such as prompt caching and server-side fallback on refusals are not
used yet. With only one real provider, the abstraction is untested against a second one.

**Update (2026-10-17):** a second provider, `OllamaProvider`, was added for free local review.
It is one class plus three settings; nothing in the pipeline changed, which is the evidence the
interface was the right size. It talks to Ollama over plain HTTP with the existing `httpx`
dependency instead of adding the `ollama` Python package.

**Revisit if** a third provider is added; consider prompt caching once real usage data exists.
