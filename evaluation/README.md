# Evaluation

How DevPilot's benchmark results are produced, stored and reproduced. Results and their
interpretation are in [docs/evaluation.md](../docs/evaluation.md).

## Layout

| Path | What it is |
|---|---|
| `datasets/v1/cases.py` | The 17 synthetic cases (13 seeded defects, 4 clean). Never edited to change scores. |
| `prompts/` | Experimental prompts used only by the benchmark (production prompts live in `backend/app/ai/`). |
| `scripts/run_eval.py` | Runs one or more configurations through the real review pipeline. |
| `scripts/scoring.py` | Matching rules (±2 lines) and the opaque, label-blind repository names. |
| `scripts/two_step.py` | Benchmark-only two-step strategy (`--strategy two-step`). |
| `scripts/run_label_blind.sh` | Runs static + 4 AI configurations × 3 with GPU monitoring and cool-downs. |
| `scripts/run_details.py` | Exports a run's database to a portable, path-free `details.json`. |
| `scripts/compare_runs.py` | Builds `reports/experiments/COMPARISON.md` from tracked files only. |
| `scripts/scan_real_code.py` | False-positive scan of DP001 / SIM115 on installed library code. |
| `scripts/repeat_v3.sh`, `scripts/ollama-serve-logged.ps1` | Historical repeat runner; Ollama with debug logging. |
| `reports/` | One folder per run (see below). Pre-fix results are kept and marked as potentially contaminated. |

## What is tracked and what is not

Each run folder contains:

| File | Tracked | Why |
|---|---|---|
| `latest.json`, `<timestamp>.json` | yes | Scores, per-case predictions, configuration, prompt hash, `label_blind` flag |
| `details.json` (`<stamp>-details.json`) | yes | Per-case model telemetry (attempts, tokens, returned / accepted / rejected findings with reasons, model summary), duplicates removed, analyzer versions, stage timings, and the full text of every saved finding. Deterministic, no paths or emails. |
| `latest.md` | yes | Human-readable table for that run |
| `gpu.csv`, `runner.log`, `ABORTED.txt` | yes | Evidence for throttling, cool-downs and aborted runs (small, path-free) |
| `eval.db` | **no** (`*.db` in `.gitignore`) | Throwaway SQLite state: contains absolute temp paths with the local username, generated user emails, and bulk (diff patches, test code) that the dataset regenerates. Its unique evidence is in `details.json`. |
| `run.log`, `*-run.log` | **no** | Console output duplicating `latest.md`; one contained a local path |

The Ollama debug log lives outside the repository; the lines supporting the HTTP 500 diagnosis are
kept in `reports/experiments/label-blind/ollama-repeat-limit-excerpt.log.txt`.

## Reproducing

All commands run from `backend/` unless noted.

**Offline, no Ollama needed:**

```bash
# Analyzer-only benchmark (writes latest.json, details.json, latest.md)
uv run python ../evaluation/scripts/run_eval.py --configs static --out ../evaluation/reports/<new-folder>

# Inspect the exact prompts the model would receive (no model call; reported as a failed run)
DEVPILOT_LLM_PROVIDER=ollama uv run python ../evaluation/scripts/run_eval.py --configs ai --dump-prompts <dir> --out <dir>

# Rebuild the comparison table from tracked files (any Python 3.12+, from the repo root)
python evaluation/scripts/compare_runs.py

# Re-export details.json from local databases (repo root)
python evaluation/scripts/run_details.py evaluation/reports

# Real-code false-positive scan (needs the backend environment)
uv run python ../evaluation/scripts/scan_real_code.py --out ../evaluation/reports/experiments/label-blind-static-v2/realcode-scan

# Tests for the harness, leakage safeguards, rules and artifacts
uv run pytest tests/test_eval_scoring.py tests/test_eval_leakage.py tests/test_eval_artifacts.py tests/test_ast_rules.py tests/test_two_step.py
```

**Needs Ollama running with `qwen2.5-coder:3b` (free, local):**

```bash
DEVPILOT_LLM_PROVIDER=ollama uv run python ../evaluation/scripts/run_eval.py --configs ai,combined --out ../evaluation/reports/<new-folder>
bash ../evaluation/scripts/run_label_blind.sh                    # full label-blind set, about 1 hour
DEVPILOT_EVAL_OUT=../evaluation/reports/experiments/<new> bash ../evaluation/scripts/run_label_blind.sh static combined-single-1
```

Runs never overwrite: the runner skips existing folders. Model outputs can vary between machines
(GPU, drivers, Ollama version), so regenerated AI runs are new evidence, not replacements for the
saved ones. `COMPARISON.md` and `scan.md` are generated; `REPORT.md` files and
`realcode-scan/classification.md` are written by hand from those generated files.

## Integrity rules the scripts enforce

- Repository names are opaque hashes, so the model never sees case IDs or labels
  (`tests/test_eval_leakage.py`).
- Every report records `"label_blind": true`; `compare_runs.py` refuses anything else.
- Failed and incomplete runs are reported as failed, never as zero findings; `compare_runs.py`
  stops if an input is missing, incomplete, or inconsistent with its `details.json`.
