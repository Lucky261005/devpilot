# v3 two-step: repeated runs

> **Historical, pre-fix result.** This run used repository names that contained the case ID, which describes the seeded defect. Its LLM scores may be influenced by that label and are not valid unbiased estimates. See `evaluation/reports/experiments/label-blind/REPORT.md` for the corrected results.

Completed 2026-10-17, 14:18Z–15:20Z: 3 AI-only and 3 combined runs, each in its own folder.
An earlier attempt at 14:03Z was stopped by GPU throttling and is kept as `ai-1-aborted/` (not
used below).

**Headline:** the AI-only result is fully repeatable (2/13 in all three runs). Combined mode beat
the analyzers once in three runs (8/13 vs 7/13). **But the benchmark leaks each case's ID, which
describes the seeded defect, into the prompt (see "Validity problem"). Every LLM number recorded
so far, including the earlier baselines, is affected.**

## Setup

Unchanged from v3: `evaluation/scripts/two_step.py`, production system prompt (sha256
`5c21f3eb540ed09c`), step-A prompt `evaluation/prompts/two_step_analysis.txt`,
`qwen2.5-coder:3b` via Ollama 0.40.5, temperature 0, `num_ctx` 16384, context chars 60000,
dataset v1, validators and scoring. **No seed is set** by the harness, so Ollama's default is used.
Hardware: GTX 1650 4 GB, 16 GB RAM; you switched the laptop to performance mode and improved
cooling before these runs.

Procedure: `bash ../evaluation/scripts/repeat_v3.sh <run>` from `backend/`, one run at a time.
Between runs I waited until the GPU was at or below 57 °C (and at least 2 minutes for the combined
runs). The runner sampled the GPU every ~10 s and would abort on throttling (>= 90% utilization at
<= 400 MHz for 3 samples) or 2 HTTP 500s. Ollama ran in a visible terminal with `OLLAMA_DEBUG=1`,
logging to `D:\ollama\server.log` (`evaluation/scripts/ollama-serve-logged.ps1`).

## Per-run results (17 cases: 13 seeded defects, 4 clean)

| Run | Detected / 13 | Recall | Precision | FP on clean | Model calls | Failures (timeouts) | Model findings returned / rejected | Dup | p50 latency | Mean tokens in / out | Throttled samples |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ai-1 | 2 | 0.154 | 1.0 | 0/4 | 33 | 1 (0) | 2 / 0 | 0 | 13.2 s | 1,265 / 388 | 0 |
| ai-2 | 2 | 0.154 | 1.0 | 0/4 | 33 | 1 (0) | 2 / 0 | 0 | 13.5 s | 1,265 / 388 | 0 |
| ai-3 | 2 | 0.154 | 1.0 | 0/4 | 33 | 1 (0) | 2 / 0 | 0 | 13.5 s | 1,265 / 388 | 0 |
| combined-1 | 7 | 0.538 | 1.0 | 0/4 | 33 | 1 (0) | 0 / 0 | 0 | 13.4 s | 1,274 / 343 | 0 |
| combined-2 | **8** | **0.615** | 1.0 | 0/4 | 33 | 1 (0) | 1 / 0 | 0 | 13.9 s | 1,302 / 391 | 0 |
| combined-3 | 7 | 0.538 | 1.0 | 0/4 | 33 | 2 (1) | 0 / 0 | 0 | 13.4 s | 1,315 / 379 | 0 |

"Model calls" counts both steps; a case whose step A fails makes one call. Precision and the
clean-case false-positive rate count analyzer and model findings together.

**Detected:**
- AI-only, all three runs: `boundary-last-index` (`xs[len(xs)]`), `security-shell-injection`.
- Combined, all three runs: the analyzers' seven (`errors-bare-except-swallows`,
  `errors-lost-exception-context`, `logic-mutable-default`, `security-shell-injection`,
  `security-sql-fstring`, `security-yaml-load`, `security-tls-verify-off`); combined-2 also
  `boundary-last-index`, which was the model's only accepted finding in combined mode.

**Never detected in any run (0/6):** `boundary-discount-threshold`,
`boundary-pagination-drops-last-page`, `resource-file-not-closed`,
`resource-connection-leak-on-error`, `logic-inverted-permission`.

## Summary

1. **Recall across runs.** AI-only: mean 0.154, range 0.154–0.154 (identical outputs, token counts
   and findings in all three). Combined: mean 0.564, range 0.538–0.615.
2. **Consistent detections.** `boundary-last-index` and `security-shell-injection` in AI-only mode
   (3/3). In combined mode, `boundary-last-index` appeared 1/3; the other seven come from the
   analyzers.
3. **Combined vs static-only 7/13.** Better once (8/13 in combined-2), equal twice. Mean +0.33
   defects per run; not a reliable improvement.
4. **Is the extra latency justified?** Not by this evidence. Two-step costs about 13–14 s per
   review vs about 1 s for analyzers alone and about 2–3 s for single-step. The only defect it adds
   over the analyzers (`xs[len(xs)]`) is caught 3/3 in AI-only but only 1/3 in combined mode, and
   the validity problem below means even that may be helped by the case ID in the prompt.
5. **Hardware and server problems.**
   - No throttling during the six completed runs: the GPU stayed at 1,680–1,785 MHz whenever it was at least 50% busy. The
     earlier aborted attempt throttled to 300 MHz (reasons `0x24`: software power cap + thermal
     slowdown) before the power-mode and cooling changes.
   - The HTTP 500 is explained. Ollama's log shows `prediction aborted, token repeat limit reached`
     for `errors-lost-exception-context`: in step A the model falls into a repetition loop, and with
     greedy decoding it does so identically every time. It failed in all six runs. It is a model
     behavior, not a server or hardware fault.
   - combined-3 also had one 120 s timeout.

## Validity problem found during these runs

The harness names each throwaway repository `<config>-<case id>`, and the pipeline puts the
repository name in the first line of the prompt (`Review: ai-boundary-last-index (diff)`). Two
consequences:

- **Defect hints reach the model.** Case IDs describe the seeded defect (`security-sql-fstring`,
  `resource-file-not-closed`, `logic-inverted-permission`) or say the change is clean
  (`clean-...`). The rule that the model must not see labels was therefore not met in **any** LLM
  run so far: the single-step baseline, the checklist experiment, v3 and these repeats.
- **AI-only and combined prompts differ.** The `ai-` / `combined-` prefix makes the prompts for
  the same case slightly different. That is the most likely reason `boundary-last-index` was found
  3/3 in AI-only but only 1/3 in combined mode, even though the analyzers report nothing for that
  case. It also shows how sensitive this model is to small prompt changes.

Production reviews are not affected: there the prompt carries the user's own repository name.
The analyzer-only results are not affected, since no model is involved.

**Proposed fix (not applied, because this experiment required an unchanged harness):** name
evaluation repositories with a neutral, non-descriptive identifier (for example `case-07`)
that is the same for every configuration, then re-run the baselines and the two-step runs.
Until then, LLM recall numbers in this project should be read as upper bounds.

## Files

- `ai-1/`, `ai-2/`, `ai-3/`, `combined-1/`, `combined-2/`, `combined-3/`: each has `latest.json`,
  a timestamped JSON, `latest.md`, `eval.db`, `run.log`, `gpu.csv`.
- `ai-1-aborted/`: the throttled attempt (with `ABORTED.txt`).
- `runner.log`: start and end times for every run.
- Ollama debug log: `D:\ollama\server.log` (outside the repository; contains the repeat-limit lines).
