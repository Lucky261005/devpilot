# Evaluation report — 2026-10-17T19:17:23Z

Dataset `v1`: 17 cases (13 with seeded defects, 4 clean). All cases are synthetic.

Environment: Python 3.12.2, Windows-11-10.0.26200-SP0, analyzers {'ruff': '0.17.1', 'bandit': '1.9.4', 'devpilot-ast': '1.0'}. Match tolerance ±2 lines.

System prompt: production (app/ai/context.py) (sha256 5c21f3eb540ed09c). Strategy: two-step. Label-blind: yes.

| Config | Status | Precision | Recall | TP | FP | FN | Dup | Clean-case FP rate | Severity match | Valid citations | p50 latency (ms) | Cost/review (USD) | Failure rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| combined (ollama: qwen2.5-coder:3b) | completed | 1.0 | 0.692 | 9 | 0 | 4 | 0 | 0.0 | 0.778 | 1.0 | 14639 | 0.0 | 0.059 |

p95 latency is omitted below 20 observations.

## Per-case results

### combined

| Case | Expected | TP | FP | FN | Predictions |
|---|---|---|---|---|---|
| boundary-discount-threshold | 1 | 0 | 0 | 1 | — |
| boundary-pagination-drops-last-page | 1 | 0 | 0 | 1 | — |
| boundary-last-index | 1 | 1 | 0 | 0 | DP001@util/seq.py:6 |
| errors-bare-except-swallows | 1 | 1 | 0 | 0 | E722@app/config.py:8 |
| errors-lost-exception-context | 1 | 1 | 0 | 0 | B904@app/fetch.py:9 |
| resource-file-not-closed | 1 | 1 | 0 | 0 | SIM115@io_utils.py:7 |
| resource-connection-leak-on-error | 1 | 0 | 0 | 1 | — |
| logic-inverted-permission | 1 | 0 | 0 | 1 | — |
| logic-mutable-default | 1 | 1 | 0 | 0 | B006@cart.py:5 |
| security-shell-injection | 1 | 1 | 0 | 0 | B602@tools/report.py:9 |
| security-sql-fstring | 1 | 1 | 0 | 0 | B608@repo/users.py:6 |
| security-yaml-load | 1 | 1 | 0 | 0 | B506@cfg.py:11 |
| security-tls-verify-off | 1 | 1 | 0 | 0 | B501@client.py:5 |
| clean-rename-variable | 0 | 0 | 0 | 0 | — |
| clean-add-typed-helper | 0 | 0 | 0 | 0 | — |
| clean-context-manager-refactor | 0 | 0 | 0 | 0 | — |
| clean-safe-subprocess | 0 | 0 | 0 | 0 | — |

