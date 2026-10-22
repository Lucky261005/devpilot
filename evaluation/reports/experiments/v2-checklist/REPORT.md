# Experiment: checklist system prompt for qwen2.5-coder:3b

> **Historical, pre-fix result.** This run used repository names that contained the case ID, which describes the seeded defect. Its LLM scores may be influenced by that label and are not valid unbiased estimates. See `evaluation/reports/experiments/label-blind/REPORT.md` for the corrected results.

Run 2026-10-17T13:21:06Z. Result: **no improvement**. The baseline stays the recorded result.

## Question

Does a system prompt that walks the model through specific defect categories, and asks it to
trace a triggering input, make `qwen2.5-coder:3b` find seeded defects without adding false
positives?

## What changed, and what did not

| | Baseline (2026-10-17T13:13:33Z) | Experiment (2026-10-17T13:21:06Z) |
|---|---|---|
| System prompt | production, `app/ai/context.py` (sha256 `5c21f3eb540ed09c`, 1,515 chars) | `evaluation/prompts/system_v2_checklist.txt` (sha256 `616e7f04b8dbfaff`) |
| User prompt, context builder, schema, validation, dedupe, scoring | unchanged | unchanged |
| Model / temperature / `num_ctx` / context chars | qwen2.5-coder:3b / 0 / 16384 / 60000 | same |
| Hardware | GTX 1650 4 GB, 16 GB RAM | same |
| Dataset | v1, 17 synthetic cases (13 defects, 4 clean) | same |

The variant keeps the production prompt's untrusted-content and citation rules, adds a
7-item checklist (boundaries, indexing/arithmetic, error handling, resources, logic regressions,
security, shared state), asks the model to trace a concrete triggering input, and states that an
empty list is correct for a clean change. Two checklist items were generalized before the run
because their first wording was close to specific seeded cases.

**Isolation.** The variant is applied only inside the benchmark process
(`--system-prompt-file`, which replaces `app.services.review.SYSTEM_PROMPT` for that process). The
application was not modified. In the AI-only configuration the harness passes no analyzers, so the
prompt's STATIC ANALYSIS section is `(none)`: the model receives no analyzer hints.

## Command

```bash
cd backend
DEVPILOT_LLM_PROVIDER=ollama uv run python ../evaluation/scripts/run_eval.py \
  --configs static,ai,combined \
  --system-prompt-file ../evaluation/prompts/system_v2_checklist.txt \
  --out ../evaluation/reports/experiments/v2-checklist
```

Wall time about 4 minutes. 51 review jobs, 34 model calls.

## Results

| Config | Prompt | Calls completed | Model findings returned / accepted / rejected | Recall | Precision | FP (clean cases) | Missed | Dup | p50 latency | Mean tokens in / out |
|---|---|---|---|---|---|---|---|---|---|---|
| ai | baseline | 17/17 | 0 / 0 / 0 | 0.0 (0/13) | — | 0 (0/4) | 13 | 0 | 2.09 s | 455 / 31 |
| ai | **checklist** | 17/17 | 0 / 0 / 0 | 0.0 (0/13) | — | 0 (0/4) | 13 | 0 | 2.25 s | 625 / 30 |
| combined | baseline | 17/17 | 4 / 4 / 0 | 0.538 (7/13) | 1.0 | 0 (0/4) | 6 | 1 | 3.27 s | 467 / 113 |
| combined | **checklist** | 17/17 | 0 / 0 / 0 | 0.538 (7/13) | 1.0 | 0 (0/4) | 6 | 0 | 3.41 s | 637 / 30 |
| static | n/a | — | — | 0.538 (7/13) | 1.0 | 0 (0/4) | 6 | 0 | 1.08 s | — |

Combined recall equals static recall in both runs: every true positive came from Ruff or Bandit.
p95 latency is not reported (17 observations per configuration; the script requires 20).

## Observations

- With the checklist prompt the model returned an empty findings list in **all 34 calls**. Output
  length was 29–31 tokens every time (the minimal valid JSON object). Summaries were variations of
  "No issues found in the reviewed code."
- The baseline prompt at least produced 4 findings in combined mode (repeats of analyzer issues);
  the checklist prompt produced none, even when analyzer findings were listed in the prompt.
- The longer prompt added about 170 input tokens and about 0.15 s of median latency.
- No call failed, timed out, or produced invalid output. No finding was rejected, because none
  were returned.

## Interpretation (hypotheses, not tested)

- A 3B model under JSON-schema-constrained decoding appears to settle on the shortest valid output.
  Changing instructions did not move it off that answer; the near-identical output length across
  all calls supports this.
- Telling the model that an empty list is correct for a clean change, in either prompt, may
  reinforce the empty answer for a model this small.
- Prompt wording is probably not the bottleneck at this model size. Options worth testing next,
  each as its own experiment against the same baseline: a larger local model (7B), asking for
  free-text reasoning first and structured output second (two calls), or giving one or two worked
  examples in the prompt.

## Limitations

- 17 synthetic cases written by one person; one run per configuration; temperature 0.
- The checklist categories were written knowing the dataset's categories, even after the two most
  case-specific items were generalized. A positive result would have needed a held-out set; a
  negative result is less affected by this.
- Results cannot be generalized to other models, real repositories, or production use.

## Files

- `20261017T132106Z.json`, `latest.json`, `latest.md`: scores and per-case predictions.
- `20261017T132106Z-eval.db`: every review job including model token counts and summaries.
- `20261017T132106Z-run.log`: console output.
- Baseline files are unchanged in `evaluation/reports/` (`20261017T131333Z*`).
