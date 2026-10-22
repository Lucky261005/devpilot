# Evaluation

## Summary of what has been measured

### Current evidence, in four tiers

How the artifacts are generated, which files are tracked, and the exact commands to reproduce them:
[evaluation/README.md](../evaluation/README.md). Every per-run number below comes from tracked JSON
(`latest.json` and `details.json`); the throwaway `eval.db` files are not needed.

Per-run numbers for every label-blind run are generated from raw files in
[evaluation/reports/experiments/COMPARISON.md](../evaluation/reports/experiments/COMPARISON.md).

**1. Original baseline (label-blind; Ruff + Bandit).** Analyzer-only 7/13 (0.538), precision 1.0,
0 false positives on the 4 clean cases. AI-only 0/13 in all 6 runs (single-step and two-step);
combined 7/13 in all 6 runs. Details below and in
[label-blind/REPORT.md](../evaluation/reports/experiments/label-blind/REPORT.md).

**2. Post-improvement results on the same dataset (development-set).** Added Ruff `SIM115` and
DevPilot rule `DP001` (`seq[len(seq)]`, `backend/app/analyzers/ast_rules.py`). **These rules were
selected after examining the analyzers' misses on this same benchmark**, so the results are
optimistic and are not an estimate of how well the rules generalize. Analyzer-only 9/13 (0.692),
precision 1.0, 0/4 false positives on clean cases; combined single-step 9/13 in 3 of 3 runs;
combined two-step 9/13 in 1 run (verified from raw files: precision 1.0, 0/4 clean-case false
positives, median 14.1 s, about 1,312 / 394 tokens in / out per case, 1 HTTP 500 in step A with no
retry; the model's one accepted finding duplicated an analyzer finding and was removed). Zero false positives on four clean cases is
weak evidence about precision in general. Report:
[label-blind-static-v2/REPORT.md](../evaluation/reports/experiments/label-blind-static-v2/REPORT.md).

**3. Real-code scan (false positives only).** Reproducible with
`evaluation/scripts/scan_real_code.py`; artifacts in
`evaluation/reports/experiments/label-blind-static-v2/realcode-scan/`. DP001: 0 hits in 1,203,805
lines (4,891 files). SIM115: 10 hits in 588,737 lines; all 10 read by hand, 9 deliberate patterns
and 1 minor real leak on an error path. This does not measure recall (no labelled bugs), and it is
mature library code, not the beginner or in-progress code the rules target.

**4. Not yet verified.** Recall on unseen defects; behavior on real pull requests; any model larger
than 3B. No independent labelled corpus exists in the repository; a plan is in the v2 report
("Independent validation").

**Does the AI add anything?** No. Across all 18 label-blind combined runs, the model's accepted
findings were always duplicates of analyzer findings, which were removed. It added **0 unique valid
findings**. AI-only found 0/13.

### Corrected, label-blind results (2026-10-17, 15:32Z–16:27Z; analyzer set before the update above)

Model `qwen2.5-coder:3b` via Ollama on a GTX 1650 4 GB laptop; dataset v1 (17 synthetic cases,
13 seeded defects, 4 clean). Static once, each AI configuration three times.

| Configuration | Recall mean (range) | Precision | FP on clean | Failures per run | p50 latency |
|---|---|---|---|---|---|
| Analyzers only (Ruff + Bandit) | 0.538 (7/13) | 1.0 | 0/4 | 0 | ~1 s |
| AI-only, single-step | 0.0 (0.0–0.0) | — (no predictions) | 0/4 | 0 | ~2.1 s |
| AI-only, two-step | 0.0 (0.0–0.0) | — (no predictions) | 0/4 | 0 | ~13.3 s |
| Analyzers + AI, single-step | 0.538 (0.538–0.538) | 1.0 | 0/4 | 0 | ~3.1 s |
| Analyzers + AI, two-step | 0.538 (0.538–0.538) | 1.0 | 0/4 | 1 (Ollama repeat-limit abort) | ~13.7 s |
| AI configurations with Claude | not run (paid API; budget is zero) | — | — | — | — |

The local 3B model added **no** valid defect beyond the analyzers in any run, and every
repetition gave identical detections. Full report, per-defect table and the fix:
[evaluation/reports/experiments/label-blind/REPORT.md](../evaluation/reports/experiments/label-blind/REPORT.md).

These numbers come from 17 small synthetic cases written for this project. They are **not**
evidence of how DevPilot performs on real repositories. One analyzer setting was changed after
looking at these same cases (see "Iteration"), which inflates the analyzer precision on this set.

### Historical LLM results: potentially contaminated by label leakage

Until 2026-10-17 15:32Z the benchmark named each test repository `<config>-<case id>`, and the
repository name appeared in the prompt. Case IDs describe the seeded defect (for example
`security-sql-fstring`) or say `clean`, so **every LLM score recorded before the fix may have been
influenced by the label.** The sections below are kept unchanged as historical records; they are not
valid unbiased estimates. Reports from before the fix have no `"label_blind": true` field.
Analyzer-only results are unaffected (no model involved; the corrected static run matched exactly).

Fix: opaque repository names (`opaque_repo_name` in `evaluation/scripts/scoring.py`), leakage tests in
`backend/tests/test_eval_leakage.py`, and a `--dump-prompts` dry run to inspect real prompts.

## Local-model run: `qwen2.5-coder:3b` (2026-10-17T13:13:33Z) — historical, pre-fix (potentially label-contaminated)

**Setup.** Ollama 0.40.5 on the same Windows 11 laptop (NVIDIA GTX 1650 4 GB, 16 GB RAM), model
`qwen2.5-coder:3b` (Q4_K_M, 3.1B parameters), `temperature: 0`, `num_ctx: 16384`, default
prompt and schema, `DEVPILOT_LLM_MAX_CONTEXT_CHARS=60000`. No code, prompt or setting was changed
before this run. Cost: 0 (local inference; electricity and hardware not counted).

Command (from `backend/`):

```bash
DEVPILOT_LLM_PROVIDER=ollama uv run python ../evaluation/scripts/run_eval.py --configs static,ai,combined
```

Total wall time 4 min 6 s; 17 cases x 3 configurations = 51 review jobs, of which 34 called the
model.

| Config | Model calls | Completed | Precision | Recall | TP | FP | FN | Dup | Clean-case FP | p50 latency | Mean tokens in / out |
|---|---|---|---|---|---|---|---|---|---|---|---|
| static | 0 | 17/17 jobs | 1.0 | 0.538 | 7 | 0 | 6 | 0 | 0/4 | 0.98 s | — |
| ai | 17 | 17/17 calls | — | 0.0 | 0 | 0 | 13 | 0 | 0/4 | 2.09 s | 455 / 31 |
| combined | 17 | 17/17 calls | 1.0 | 0.538 | 7 | 0 | 6 | 1 | 0/4 | 3.27 s | 467 / 113 |

p95 is not reported: each configuration has 17 observations and the script only reports p95 at
20 or more. The first AI call took 80.4 s (loading the model into GPU memory); the next slowest
calls took 12–19 s and most 2–3 s.

**Model findings.** AI-only: the model returned **0 findings in all 17 cases** (16 summaries
said "No actionable defects found"), so nothing was rejected and nothing was found.
Combined: the model returned 4 findings in 3 cases (mutable default, SQL f-string, TLS verify).
All 4 passed source validation (valid citation rate 1.0, 0 rejected), but all 4 described issues
the analyzers had **already reported** and were listed in the prompt. Three were removed by
deduplication and one remained as a duplicate of an already-matched reference (Dup = 1). The model
added **no new true positives**.

**Failure analysis (hypotheses, not yet tested).**
- The model only flagged issues when the analyzer results in the prompt pointed at them, despite
  the instruction not to repeat them. It did not find any of the six semantic defects
  (off-by-one, dropped page, `xs[len(xs)]`, two resource leaks, inverted permission).
- The system prompt strongly permits zero findings ("Returning zero findings is correct...").
  A 3B model may read this as the safe default. Mean output was 31 tokens: the empty schema.
- Constrained JSON decoding may push a small model toward the shortest valid object.
- A larger model (7B) or prompt changes could behave differently; neither has been measured.

**What this does and does not show.** The local pipeline works end to end: every call
completed, outputs were valid JSON, citations were valid, and nothing was invented. On these 17
synthetic cases, this 3B model adds no detection value over Ruff and Bandit. This says nothing
about larger or hosted models, and 17 synthetic cases cannot establish production readiness.

Raw outputs preserved in `evaluation/reports/`: `20261017T131333Z.json` (scores and per-case
predictions), `20261017T131333Z-ollama.md` (table), `20261017T131333Z-ollama-eval.db` (SQLite
copy of every review job, including model token counts, summaries and rejection data) and
`20261017T131333Z-ollama-run.log`.

### Experiment: checklist system prompt (2026-10-17T13:21:06Z) — historical, pre-fix (potentially label-contaminated)

A variant system prompt (`evaluation/prompts/system_v2_checklist.txt`) with a defect-category
checklist was tested against the same model, dataset and settings, applied only inside the
benchmark process via `--system-prompt-file`. **No improvement:** the model returned zero findings
in all 34 calls (recall 0.0 AI-only; combined = analyzer recall 0.538; no false positives;
p50 2.25 s / 3.41 s). The production prompt was not changed. Full report:
[evaluation/reports/experiments/v2-checklist/REPORT.md](../evaluation/reports/experiments/v2-checklist/REPORT.md).

### Experiment v3: two-step reasoning (2026-10-17T13:41Z and 13:58Z) — historical, pre-fix (potentially label-contaminated)

Benchmark-only strategy (`run_eval.py --strategy two-step`): a plain-text analysis call, then the
normal structured call with the notes attached. Same model, dataset and scoring; production code
unchanged. AI-only: **2/13 found** (recall 0.154, precision 1.0, 0 clean-case false positives,
1 of 17 cases failed with an Ollama HTTP 500). Combined: 7/13, the same as analyzers alone (the
model's one finding was a duplicate). Median latency rose from about 2 s to about 15.5 s per review.
One semantic defect found in the AI-only run was missed in the combined run with the same prompt,
so the gain is not yet shown to be repeatable. Not adopted. Full report:
[evaluation/reports/experiments/v3-two-step/REPORT.md](../evaluation/reports/experiments/v3-two-step/REPORT.md).

### Experiment v3, repeated runs (2026-10-17, 14:18Z-15:20Z) — historical, pre-fix (potentially label-contaminated)

Three AI-only and three combined two-step runs, one at a time with cool-downs, after the laptop
was set to performance mode (an earlier attempt that throttled is kept but unused). AI-only:
**2/13 in all three runs** (identical outputs). Combined: 7, 8 and 7 of 13 (mean 0.564; one run
above the analyzers' 7). No false positives on clean cases in any run; one case fails every time
because the model hits Ollama's token-repeat limit (the HTTP 500). Median latency about 13.5 s per
review in both modes.

**Validity problem found:** the harness names each test repository after the case ID (for
example `ai-security-sql-fstring`), and that name is in the prompt. Case IDs describe the seeded
defect, or say `clean`, so every LLM run so far, including the single-step baselines, received a
hint, and AI-only and combined prompts were not identical. LLM recall figures should be read as
upper bounds until the harness uses neutral names and the runs are repeated. Analyzer-only results
and production reviews are unaffected. Details:
[evaluation/reports/experiments/v3-two-step/repeats/REPORT.md](../evaluation/reports/experiments/v3-two-step/repeats/REPORT.md).

**Hardware note:** in Balanced mode this laptop's GPU throttled to 300 MHz after about 3 minutes
of sustained inference. In performance mode with better cooling and cool-downs between runs, six
consecutive runs completed at full clock.

## Dataset (`evaluation/datasets/v1/cases.py`)

- **Source and licensing:** all cases were written for this project (same license as the repo).
  No third-party code. No naturally occurring defects are included yet.
- **Shape:** each case is a `before` and `after` file set. The harness commits both to a new Git
  repo and reviews `HEAD~1..HEAD`, so only the change is reviewed, as in a PR.
- **Labels:** `expected` lists defects on the new side with path, line range, category, severity,
  a description and a severity rationale. `expected: []` marks a clean change.
- **Composition (17 cases):**

| Group | Cases | Examples |
|---|---|---|
| Boundaries / conditions | 3 | `>` vs `>=` threshold, last page dropped, `xs[len(xs)]` |
| Error handling | 2 | bare `except`, re-raise without `from` |
| Resources | 2 | file never closed, connection leaked on exception |
| Logic regressions | 2 | `or` → `and` in a permission check, mutable default argument |
| Security | 4 | `shell=True`, SQL via f-string, `yaml.Loader`, `verify=False` |
| Clean changes | 4 | rename, typed helper, context-manager refactor, safe list-form subprocess |

The labels were written by the author of the cases (one person, no second reviewer), so label
quality is itself unverified. Missing-test detection is not evaluated.

## Configurations compared

All run through the real pipeline (`process_job`) with identical cases and settings:

1. **static** — Ruff + Bandit, no LLM.
2. **ai** — LLM only (`analyzers=[]`).
3. **combined** — Ruff + Bandit, then LLM with analyzer results in the prompt, then dedupe.

The harness refuses to fabricate results: a configuration that can't run is recorded as
`not_run` with the reason.

## Metrics

A prediction **matches** a reference defect if the path is equal and its line range, widened by
±2 lines, intersects the reference range (`evaluation/scripts/scoring.py`).

| Metric | Definition |
|---|---|
| TP / FP / FN | Matched first time / matched nothing / reference defects never matched |
| Duplicates | Predictions matching an already-matched reference |
| Precision | TP / (TP + FP) |
| Recall | TP / (TP + FN) |
| Clean-case false-positive rate | Share of clean cases with ≥1 FP |
| Duplicate rate | Duplicates / all predictions |
| Severity exact match | Share of TPs whose severity equals the reference |
| Valid citation rate | (LLM only) findings passing validation / findings returned by the model |
| Useful findings per review | TP / cases |
| Latency p50 / p95 | Wall-clock per case including git + analyzers (+ LLM); p95 only with ≥20 observations |
| Tokens and cost per review | Mean input/output tokens; cost from the cached Anthropic price table in the script |
| Failure / timeout rate | Jobs that failed or whose LLM call failed |

## Results: analyzers only (run 2026-10-17T08:25:28Z, Windows 11, Python 3.12.2, Ruff 0.17.1, Bandit 1.9.4)

| Metric | Value |
|---|---|
| TP / FP / FN / duplicates | 7 / 0 / 6 / 0 |
| Precision | 1.0 |
| Recall | 0.538 |
| Clean-case FP rate | 0.0 (0 of 4) |
| Severity exact match | 0.714 (5 of 7; B904 rated medium vs reference low, B608 SQL injection rated medium vs reference high) |
| Useful findings per review | 0.41 |
| Latency p50 | ≈1.1 s per case (p95 not reported, n = 17) |
| Failures | 0 |

Sample size is tiny: one more or one fewer detection moves recall by ~0.08. No confidence
intervals are reported because they would be very wide and the cases are not a random sample of
anything.

**Detected:** bare except (E722), lost exception context (B904), mutable default (B006), shell
injection (B602), SQL f-string (B608), `yaml.Loader` (B506), `verify=False` (B501).

**Missed (all six need semantic understanding):** threshold off-by-one, dropped last page,
`xs[len(xs)]`, unclosed file, connection leak on error, inverted permission logic. These are the
cases where the LLM configurations are expected to add value, which is the hypothesis the
`ai`/`combined` runs are meant to test.

## Iteration based on observed results

First run (kept as `evaluation/reports/baseline-before-bandit-tuning.md`): precision 0.778,
2 FPs, both on the clean `safe-subprocess` case: Bandit B603 ("subprocess call — check for
execution of untrusted input") and B607 ("partial executable path") on a list-form
`subprocess.run(['git', ...])`. These rules flag every subprocess call rather than defects, so
they were added to `BANDIT_SKIP` (with B101/B403/B404). Second run: precision 1.0, recall
unchanged.

Caveat: this setting was chosen by looking at the evaluation set. A held-out set would be needed
to claim it generalizes.

## Reproducing

```bash
cd backend
uv sync
uv run python ../evaluation/scripts/run_eval.py --configs static            # no key needed
ANTHROPIC_API_KEY=sk-ant-... uv run python ../evaluation/scripts/run_eval.py --configs static,ai,combined
```

Free, local alternative (after installing Ollama and `ollama pull qwen2.5-coder:3b`):

```bash
DEVPILOT_LLM_PROVIDER=ollama uv run python ../evaluation/scripts/run_eval.py --configs static,ai,combined
```

Local runs report cost as `0.0` (no API charge; electricity and hardware are not counted) and
record the provider and model in each row. If every LLM call in a configuration fails (for
example Ollama is not running), that configuration is reported as `failed` with the reason instead
of a row of zeros. A **failure rate** column shows partial failures.

Each run writes `evaluation/reports/<UTC timestamp>.json`, `latest.json` and `latest.md`. The
model is taken from `DEVPILOT_LLM_MODEL` (default `claude-opus-5-5`, effort `medium`).

## Limitations

- Synthetic, single-author, small (17 cases, 13 defects). Seeded bugs are easier to localize than
  real ones and appear in tiny files with no surrounding complexity.
- No natural defects from real PRs yet. Adding cases from permissively licensed projects (with
  the commit, license and a link recorded per case) is the main next step.
- Line-overlap matching can credit a finding that cites the right line for the wrong reason;
  descriptions are not graded.
- LLM results will vary run to run; the harness runs each case once. Multiple runs per case are
  needed before comparing LLM configurations.
- Analyzer severity is mapped by DevPilot from the tools' own levels, so "severity match" partly
  measures that mapping.
