# Evaluation report — 2026-10-17T19:01:43Z

Dataset `v1`: 17 cases (13 with seeded defects, 4 clean). All cases are synthetic.

Environment: Python 3.12.2, Windows-11-10.0.26200-SP0, analyzers {'ruff': '0.17.1', 'bandit': '1.9.4', 'devpilot-ast': '1.0'}. Match tolerance ±2 lines.

System prompt: production (app/ai/context.py) (sha256 5c21f3eb540ed09c). Strategy: two-step. Label-blind: yes.

| Config | Status | Precision | Recall | TP | FP | FN | Dup | Clean-case FP rate | Severity match | Valid citations | p50 latency (ms) | Cost/review (USD) | Failure rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ai (ollama: qwen2.5-coder:3b) | completed | — | 0.0 | 0 | 0 | 13 | 0 | 0.0 | — | — | 13936 | 0.0 | 0.0 |

p95 latency is omitted below 20 observations.

## Per-case results

### ai

| Case | Expected | TP | FP | FN | Predictions |
|---|---|---|---|---|---|
| boundary-discount-threshold | 1 | 0 | 0 | 1 | — |
| boundary-pagination-drops-last-page | 1 | 0 | 0 | 1 | — |
| boundary-last-index | 1 | 0 | 0 | 1 | — |
| errors-bare-except-swallows | 1 | 0 | 0 | 1 | — |
| errors-lost-exception-context | 1 | 0 | 0 | 1 | — |
| resource-file-not-closed | 1 | 0 | 0 | 1 | — |
| resource-connection-leak-on-error | 1 | 0 | 0 | 1 | — |
| logic-inverted-permission | 1 | 0 | 0 | 1 | — |
| logic-mutable-default | 1 | 0 | 0 | 1 | — |
| security-shell-injection | 1 | 0 | 0 | 1 | — |
| security-sql-fstring | 1 | 0 | 0 | 1 | — |
| security-yaml-load | 1 | 0 | 0 | 1 | — |
| security-tls-verify-off | 1 | 0 | 0 | 1 | — |
| clean-rename-variable | 0 | 0 | 0 | 0 | — |
| clean-add-typed-helper | 0 | 0 | 0 | 0 | — |
| clean-context-manager-refactor | 0 | 0 | 0 | 0 | — |
| clean-safe-subprocess | 0 | 0 | 0 | 0 | — |

