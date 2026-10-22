# Experiment v3: two-step reasoning with qwen2.5-coder:3b

> **Historical, pre-fix result.** This run used repository names that contained the case ID, which describes the seeded defect. Its LLM scores may be influenced by that label and are not valid unbiased estimates. See `evaluation/reports/experiments/label-blind/REPORT.md` for the corrected results.

AI-only run 2026-10-17T13:41:17Z; combined run 2026-10-17T13:58:15Z.
Result: **small, unconfirmed gain in AI-only mode (2/13), no gain in combined mode, at about 7x the
latency.** Not adopted; the production pipeline is unchanged.

## Design

Both steps go to the same local model (`qwen2.5-coder:3b`, Ollama, temperature 0,
`num_ctx` 16384, context chars 60000, GTX 1650 4 GB / 16 GB RAM).

- **Step A (analysis):** system prompt `evaluation/prompts/two_step_analysis.txt`; user message is
  exactly the prompt the pipeline builds. Plain text, no schema, capped at 1,024 output tokens.
  It asks the model to state each changed function's intent, walk its control flow, try boundary
  inputs, and write file, lines, code, triggering input and failure for each suspected defect.
- **Step B (structured):** the normal call, with the **production** system prompt (sha256
  `5c21f3eb540ed09c`), the `AIReview` schema and the usual retry rules. The user message is the
  original prompt plus the step-A notes inside `<analysis_notes>`, with an instruction to report
  only findings the shown code confirms (exact lines, verbatim evidence, triggering input).
  Zero findings stays an allowed answer. The notes are fenced like repository content.
- Validation, deduplication and scoring are unchanged.

**Isolation.** The strategy is `evaluation/scripts/two_step.py` (`TwoStepOllamaProvider`), passed
to the pipeline as `provider_factory` only when `run_eval.py --strategy two-step` is used. No
application file was changed, and normal reviews still use the single-step provider. In the
AI-only configuration the harness runs no analyzers, so the prompt's STATIC ANALYSIS section is
`(none)`: no analyzer output or labels reach the model.

## Commands

```bash
cd backend
DEVPILOT_LLM_PROVIDER=ollama uv run python ../evaluation/scripts/run_eval.py \
  --configs ai --strategy two-step --out ../evaluation/reports/experiments/v3-two-step
DEVPILOT_LLM_PROVIDER=ollama uv run python ../evaluation/scripts/run_eval.py \
  --configs combined --strategy two-step --out ../evaluation/reports/experiments/v3-two-step/combined
```

## Results compared with earlier runs (same dataset v1: 17 cases, 13 defects, 4 clean)

| Config | Strategy | Inference calls | Completed | Model findings returned / accepted / rejected | TP | FP (clean) | Missed | Dup | Recall | Precision | p50 latency | Mean tokens in / out |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ai | single, production prompt | 17 | 17/17 | 0 / 0 / 0 | 0 | 0 (0/4) | 13 | 0 | 0.0 | — | 2.09 s | 455 / 31 |
| ai | single, checklist prompt | 17 | 17/17 | 0 / 0 / 0 | 0 | 0 (0/4) | 13 | 0 | 0.0 | — | 2.25 s | 625 / 30 |
| ai | **two-step** | 33 (16 x 2 + 1 failed in step A) | 16/17 | 2 / 2 / 0 | **2** | 0 (0/4) | 11 | 0 | **0.154** | 1.0 | 15.5 s | 1,265 / 388 |
| combined | single, production prompt | 17 | 17/17 | 4 / 4 / 0 | 7 | 0 (0/4) | 6 | 1 | 0.538 | 1.0 | 3.27 s | 467 / 113 |
| combined | single, checklist prompt | 17 | 17/17 | 0 / 0 / 0 | 7 | 0 (0/4) | 6 | 0 | 0.538 | 1.0 | 3.41 s | 637 / 30 |
| combined | **two-step** | 34 | 17/17 | 1 / 1 / 0 | 7 | 0 (0/4) | 6 | 0 | 0.538 | 1.0 | 15.6 s | 1,337 / 423 |
| static | — | 0 | — | — | 7 | 0 (0/4) | 6 | 0 | 0.538 | 1.0 | ~1.0 s | — |

Token figures are per case and include both steps. p95 is not reported (17 observations per run;
the script requires 20). All model findings that were returned passed source validation (valid
citation rate 1.0). Cost: 0 (local inference).

**AI-only details.** The two true positives were `boundary-last-index` (`xs[len(xs)]` always raises,
a semantic defect neither analyzer detects) and `security-shell-injection` (also found by Bandit).
One case (`errors-lost-exception-context`) failed: Ollama returned HTTP 500 to the step-A call. It
is counted as a failure (failure rate 0.059), not as zero findings. The server log was not captured
(Ollama was started without a visible console), so the cause is unknown.

**Combined details.** The model returned one finding, a duplicate of an analyzer finding, which
deduplication removed. Combined recall equals analyzer-only recall: the model added no true
positive. `boundary-last-index` was **not** found in this run, although its prompt is the same as
in the AI-only run (the analyzers report nothing for that case).

## Run conditions and an aborted attempt

The first combined attempt (13:44Z) was stopped after 3 cases: two calls hit the 120 s timeout and
`nvidia-smi` showed the GPU at 99% utilization but held at 300 MHz. The laptop was on mains power on
the Balanced plan; the cause of the clock limit was not identified and no setting was changed.
After it cleared (a direct test call ran at 1,380–1,770 MHz in the normal 6–8 s), combined was
re-run from scratch. The aborted run's data is kept as `combined-aborted-eval.db` and is not used
in any result above.

## Interpretation

- Splitting reasoning from structured output is the first change that got the 3B model to report
  any defect on its own, and the one semantic catch (`xs[len(xs)]`) is the kind of defect the
  analyzers cannot see.
- The gain is fragile: the same case was found in one run and missed in the next with an identical
  prompt. Greedy decoding on GPU is not guaranteed to be bit-for-bit repeatable, and a single run per
  configuration cannot separate a real effect from run-to-run variation.
- In combined mode the model added nothing beyond the analyzers.
- 2 true positives out of 13 on 17 synthetic cases is far too little evidence for any claim about
  real repositories or production readiness.

## Is the extra cost justified?

**Not yet.** Two-step costs about 7x the latency (2.1 s to 15.5 s median per review on this
GPU), about 2.8x the input tokens and about 12x the output tokens, and introduced one failure. The
measured benefit is +2 true positives in AI-only mode (one of them already covered by Bandit) and
**zero** in the combined mode that the product actually uses. Inference is free here, so the real
cost is waiting time; at roughly 15 s per review on this hardware that might be acceptable later,
but only if the gain is shown to be repeatable.

Recommended before any adoption: repeat the AI-only and combined two-step runs at least 3 times each
and report the spread of TP per case; investigate the HTTP 500; and only then consider exposing
two-step as an opt-in setting.

## Files

- `20261017T134117Z.json`, `latest.json`, `latest.md`, `ai-only-eval.db`, `ai-only-run.log`: AI-only run.
- `combined/`: combined run (`latest.json`, `latest.md`, `20261017T135815Z.json`, `combined-eval.db`, `combined-run.log`).
- `combined-aborted-eval.db`: the throttled attempt (evidence only).
- Strategy code: `evaluation/scripts/two_step.py`; step-A prompt: `evaluation/prompts/two_step_analysis.txt`.
- Tests: `backend/tests/test_two_step.py`.
