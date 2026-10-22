# Corrected, label-blind benchmark (2026-10-17, 15:32Z–16:27Z)

These are the first LLM results in this project measured **without** the case ID leaking into the
prompt. They supersede all earlier LLM scores, which are kept as historical, potentially
contaminated results.

**Result: with `qwen2.5-coder:3b`, no configuration found any defect beyond what Ruff and Bandit
already find.** AI-only recall was 0/13 in all six AI-only runs (single-step and two-step).
Combined recall equalled the analyzers' 7/13 in all six combined runs. No configuration produced a
false positive.

## What was fixed

Before: the harness named each throwaway repository `<config>-<case id>` (for example
`ai-security-sql-fstring`). The review pipeline puts the repository name in the prompt's first line,
so the model saw a description of the seeded defect, or `clean`, for every case.

After (`evaluation/scripts/run_eval.py`, `evaluation/scripts/scoring.py`):

- Repository name = `opaque_repo_name(case_id)` = `repo-` + the first 8 hex characters of
  sha256(`devpilot-eval:<case id>`). It is one-way, identical across configurations, and used for the
  repository folder too. Each configuration has its own evaluation user, so names do not collide.
- Case IDs, labels and expected findings stay in the evaluator's own data and are used only for
  scoring after the review.
- Every report records `"label_blind": true`; reports without it are pre-fix.
- `--dump-prompts DIR`: a dry run through the real pipeline that writes the exact prompts and calls
  no model (it is reported as a failed run, never as zero findings).

Unchanged: dataset `v1` (`cases.py`, sha256 prefix `e1a43810`, not modified since before the first
benchmark), defect implementations, expected findings, scoring rules (`score`, ±2-line tolerance),
production system prompt (sha256 `5c21f3eb540ed09c`), validators, deduplication, model
(`qwen2.5-coder:3b`, Ollama 0.40.5), temperature 0, `num_ctx` 16384, context chars 60000, the
two-step strategy and its step-A prompt, application code.

**Checks before the runs.**
- `backend/tests/test_eval_leakage.py` (5 tests):
  - names are opaque, unique and deterministic;
  - a name does not change when a case's label or expected findings change;
  - the rendered prompt for every case contains no case ID, and its title line contains no ID word
    or `clean`/`synthetic`/`expected`/`seeded`/`defect`;
  - everything outside the repository content is the same template for all 17 cases;
  - the rendered prompt is byte-identical after flipping a case's label;
  - a guard test confirms the old naming would be caught.
- **Dry run:** 17 prompts per configuration were inspected (a defective, a clean and a combined case).
  - AI-only and combined prompts were byte-identical for the 10 cases without analyzer findings. The
    other 7 differ only by the analyzer findings, which combined mode lists by design.
- **Static baseline re-run:** 7/13, with per-case predictions identical to the historical static run.
  The fix does not affect it.

Remaining information the model legitimately sees: the code itself, file paths from the dataset
(for example `util/seq.py`, `repo/users.py`), and, in combined mode, the analyzer findings.

## Commands

```bash
cd backend
bash ../evaluation/scripts/run_label_blind.sh            # static, then 4 configurations x 3
# one run: bash ../evaluation/scripts/run_label_blind.sh ai-two-1
# prompt dry run: DEVPILOT_LLM_PROVIDER=ollama uv run python ../evaluation/scripts/run_eval.py \
#   --configs ai --dump-prompts <dir> --out <dir>
```

The runner waited for the GPU to be at or below 57 °C and at least 90 s between runs. It sampled
temperature, utilization, clock and power every ~10 s (`gpu.csv` per run), and would have stopped
only the affected run on throttling, a 6-minute stall, or 3 HTTP 500s. **None of the 13 runs was
stopped.** The lowest clock while the GPU was at least 50% busy was 1,665 MHz; the peak temperature
was 80 °C. The laptop was plugged in, in performance mode.

## Results (17 cases: 13 seeded defects, 4 clean)

| Run | Detected / 13 | Recall | Precision | FP on clean | Model calls | Failures | Model findings returned / accepted / rejected | Dup removed | p50 latency | Tokens in / out |
|---|---|---|---|---|---|---|---|---|---|---|
| static | 7 | 0.538 | 1.0 | 0/4 | 0 | 0 | — | 0 | ~1 s | — |
| ai-single-1 | 0 | 0.0 | — | 0/4 | 17 | 0 | 0 / 0 / 0 | 0 | 2.25 s | 457 / 31 |
| ai-single-2 | 0 | 0.0 | — | 0/4 | 17 | 0 | 0 / 0 / 0 | 0 | 2.09 s | 457 / 31 |
| ai-single-3 | 0 | 0.0 | — | 0/4 | 17 | 0 | 0 / 0 / 0 | 0 | 2.06 s | 457 / 31 |
| ai-two-1 | 0 | 0.0 | — | 0/4 | 34 | 0 | 0 / 0 / 0 | 0 | 13.4 s | 1,269 / 354 |
| ai-two-2 | 0 | 0.0 | — | 0/4 | 34 | 0 | 0 / 0 / 0 | 0 | 13.2 s | 1,271 / 356 |
| ai-two-3 | 0 | 0.0 | — | 0/4 | 34 | 0 | 0 / 0 / 0 | 0 | 13.2 s | 1,271 / 356 |
| combined-single-1 | 7 | 0.538 | 1.0 | 0/4 | 17 | 0 | 2 / 2 / 0 | 2 | 3.16 s | 469 / 77 |
| combined-single-2 | 7 | 0.538 | 1.0 | 0/4 | 17 | 0 | 2 / 2 / 0 | 2 | 3.08 s | 469 / 77 |
| combined-single-3 | 7 | 0.538 | 1.0 | 0/4 | 17 | 0 | 2 / 2 / 0 | 2 | 2.97 s | 469 / 77 |
| combined-two-1 | 7 | 0.538 | 1.0 | 0/4 | 33 | 1 (HTTP 500) | 1 / 1 / 0 | 1 | 14.0 s | 1,299 / 389 |
| combined-two-2 | 7 | 0.538 | 1.0 | 0/4 | 33 | 1 (HTTP 500) | 1 / 1 / 0 | 1 | 13.7 s | 1,296 / 387 |
| combined-two-3 | 7 | 0.538 | 1.0 | 0/4 | 33 | 1 (HTTP 500) | 1 / 1 / 0 | 1 | 13.3 s | 1,295 / 385 |

Tokens are per case and include both steps for two-step runs. No timeouts occurred. p95 is not
reported (17 observations per run). Cost 0 (local inference). Every model finding returned was
accepted by source validation and then removed as a duplicate of an analyzer finding, so model
findings contributed no true positive in any run.

## Summary across repetitions

| Configuration | Recall mean (range) | Missed (mean) | FP on clean | Failures per run | p50 latency | vs static 7/13 |
|---|---|---|---|---|---|---|
| Static only | 0.538 (one run) | 6 | 0/4 | 0 | ~1 s | — |
| AI-only, single-step | 0.0 (0.0–0.0) | 13 | 0/4 | 0 | ~2.1 s | −7 |
| AI-only, two-step | 0.0 (0.0–0.0) | 13 | 0/4 | 0 | ~13.3 s | −7 |
| Combined, single-step | 0.538 (0.538–0.538) | 6 | 0/4 | 0 | ~3.1 s | ±0 |
| Combined, two-step | 0.538 (0.538–0.538) | 6 | 0/4 | 1 | ~13.7 s | ±0 |

## Per-defect detection frequency (out of 3 runs)

| Defect | AI single | AI two-step | Combined single | Combined two-step | Static |
|---|---|---|---|---|---|
| boundary-discount-threshold | 0/3 | 0/3 | 0/3 | 0/3 | no |
| boundary-pagination-drops-last-page | 0/3 | 0/3 | 0/3 | 0/3 | no |
| boundary-last-index | 0/3 | 0/3 | 0/3 | 0/3 | no |
| errors-bare-except-swallows | 0/3 | 0/3 | 3/3 | 3/3 | yes |
| errors-lost-exception-context | 0/3 | 0/3 | 3/3 | 3/3 | yes |
| resource-file-not-closed | 0/3 | 0/3 | 0/3 | 0/3 | no |
| resource-connection-leak-on-error | 0/3 | 0/3 | 0/3 | 0/3 | no |
| logic-inverted-permission | 0/3 | 0/3 | 0/3 | 0/3 | no |
| logic-mutable-default | 0/3 | 0/3 | 3/3 | 3/3 | yes |
| security-shell-injection | 0/3 | 0/3 | 3/3 | 3/3 | yes |
| security-sql-fstring | 0/3 | 0/3 | 3/3 | 3/3 | yes |
| security-yaml-load | 0/3 | 0/3 | 3/3 | 3/3 | yes |
| security-tls-verify-off | 0/3 | 0/3 | 3/3 | 3/3 | yes |

Every detection in combined mode is an analyzer detection.

## HTTP 500 investigation

The Ollama server log (`D:\ollama\server.log`, debug level) records
`prediction aborted, token repeat limit reached` for each HTTP 500: nine times today in total, three
of them in this corrected set. In the corrected runs it happened only in combined two-step, always
on `errors-lost-exception-context` during step A. That prompt includes Bandit's B904 finding. The
model starts repeating the same tokens, Ollama stops generation at its repeat limit and returns 500,
and with greedy decoding (temperature 0) this happens identically every run. Before the fix it also
happened in AI-only mode, where the prompt contained the old case name. It is a model behavior
triggered by specific prompt text, not a server or hardware fault. It is counted as a failure, and
generation settings were not changed.

## Conclusions

1. **The earlier positive results were produced by the label leak.** Pre-fix two-step AI-only found
   2/13 in four of four runs (`boundary-last-index`, `security-shell-injection`). Label-blind, it
   found 0/13 in three of three. The one pre-fix combined run that scored 8/13 is also not
   reproduced (7/13 in all three).
2. **Run-to-run variation is negligible** at temperature 0 once the prompt is fixed. All three
   repetitions of each configuration gave identical detections, and nearly identical token counts.
3. **Combined mode never improves on static-only 7/13.**
4. **The extra latency is not justified.** Single-step adds about 2 s and two-step about 13 s per
   review, for zero additional valid defects with this model.
5. **Hardware:** no throttling in performance mode with cool-downs. One repeatable server error
   (the repeat-limit abort), explained above.

The local 3B model, as configured here, adds no measurable review value on this dataset. This does
not tell us how larger local models or hosted models would perform, and 17 synthetic cases are not
evidence about real repositories.

## Files

Each run folder under `evaluation/reports/experiments/label-blind/` contains `latest.json`, a
timestamped JSON (`"label_blind": true`), `latest.md`, `eval.db`, `run.log` and `gpu.csv`.
`runner.log` has start and end times. Runner: `evaluation/scripts/run_label_blind.sh`.

## Update (2026-10-17, later the same day)

This report's runs used the **original** analyzer set (Ruff + Bandit) and are kept as they are.
The analyzers were then extended (Ruff SIM115 and DevPilot rule DP001), and static and combined
runs were repeated with the same label-blind harness:
[`label-blind-static-v2/REPORT.md`](../label-blind-static-v2/REPORT.md). Analyzer-only recall went
from 7/13 to 9/13 on this same dataset, which is a development-set result because the rules were
chosen after seeing these misses. A per-run comparison of every label-blind run is generated from
the raw files in [`../COMPARISON.md`](../COMPARISON.md) (`evaluation/scripts/compare_runs.py`).

## Follow-up note (2026-10-18): HTTP 500 evidence

The "nine times today" count above was correct when this report was written. The supporting log
lines are now kept in [`ollama-repeat-limit-excerpt.log.txt`](ollama-repeat-limit-excerpt.log.txt).
By the end of 2026-10-17 the log held 10 repeat-limit aborts, each followed by an HTTP 500 (6 in the
v3 repeats, 3 in this report's combined two-step runs, 1 in `label-blind-static-v2/combined-two-1`),
plus one more HTTP 500 after 2m0s, which is the 120 s client timeout recorded in v3 repeats
`combined-3`. Per-case telemetry for every run is in each run folder's `details.json`.
