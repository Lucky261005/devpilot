# ADR 0003: Combine deterministic analyzers with an LLM, and keep them distinguishable

**Status:** accepted (2026-10-17)

**Context.** Analyzers are precise and cheap but only see patterns (on the v1 benchmark they found
7 of 13 seeded defects, all pattern-shaped). LLMs can reason about intent (off-by-one, inverted
conditions) but produce unsupported or mislocated claims and cost money per call.

**Options.** Analyzer only; LLM only; both merged indistinguishably; both, kept separate.

**Decision.** Run analyzers first. Give the LLM a bounded, line-numbered context plus the analyzer
results marked "already reported". Validate every model finding against the source (path, lines,
quoted evidence). Merge with deduplication where analyzer findings win. Label every finding with
its source; model findings are shown as hypotheses.

**Benefits.** The product stays useful without an API key. Analyzer results cannot be corrupted by
prompt injection. Model claims that cite non-existent code never reach the user. Feedback is
recorded per analyzer/model version so each source can be judged separately.

**Costs.** More pipeline code. Evidence matching rejects real findings when the model paraphrases
code instead of quoting it. One LLM call per review means large changes are truncated.

**Revisit if** measurements show validation is too strict (correct findings rejected), or that
per-file calls give better recall at acceptable cost.
