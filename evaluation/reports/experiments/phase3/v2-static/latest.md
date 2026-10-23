# Evaluation report — 2026-10-22T22:26:09Z

Dataset `v2`: 17 cases (12 with seeded defects, 5 clean). All cases are synthetic.

Environment: Python 3.12.2, Windows-11-10.0.26200-SP0, analyzers {'ruff': '0.17.1', 'bandit': '1.9.4', 'devpilot-ast': '1.0'}. Match tolerance ±2 lines.

System prompt: production v1 (app/ai/context.py) (sha256 5c21f3eb540ed09c), context: changed. Strategy: single. Label-blind: yes.

| Config | Status | Precision | Recall | TP | FP | FN | Dup | Clean-case FP rate | Severity match | Valid citations | p50 latency (ms) | Cost/review (USD) | Failure rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| static | completed | 1.0 | 0.167 | 2 | 0 | 10 | 0 | 0.0 | 0.5 | — | 1125 | — | 0.0 |

p95 latency is omitted below 20 observations.

## Per-case results

### static

| Case | Expected | TP | FP | FN | Predictions |
|---|---|---|---|---|---|
| mf-timeout-units | 1 | 0 | 0 | 1 | — |
| mf-none-return-unchecked | 1 | 0 | 0 | 1 | — |
| mf-swapped-arguments | 1 | 0 | 0 | 1 | — |
| mf-unhandled-keyerror | 1 | 0 | 0 | 1 | — |
| rw-retry-count-off-by-one | 1 | 0 | 0 | 1 | — |
| rw-naive-vs-aware-datetime | 1 | 0 | 0 | 1 | — |
| rw-delete-while-iterating | 1 | 0 | 0 | 1 | — |
| rw-average-of-empty | 1 | 0 | 0 | 1 | — |
| sec-path-traversal | 1 | 0 | 0 | 1 | — |
| sec-pickle-from-cookie | 1 | 1 | 0 | 0 | B301@session_store.py:5 |
| sec-jwt-signature-ignored | 1 | 0 | 0 | 1 | — |
| rw-default-arg-evaluated-once | 1 | 1 | 0 | 0 | B008@audit.py:4 |
| clean-parameterized-sql | 0 | 0 | 0 | 0 | — |
| clean-log-and-reraise | 0 | 0 | 0 | 0 | — |
| clean-guarded-division | 0 | 0 | 0 | 0 | — |
| clean-multifile-correct-call | 0 | 0 | 0 | 0 | — |
| clean-multifile-none-handled | 0 | 0 | 0 | 0 | — |

