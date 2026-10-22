# Static-analysis coverage improvement (label-blind, 2026-10-17 17:38Z–17:56Z)

**Result:** analyzer-only recall rose from **7/13 (0.538) to 9/13 (0.692)**, with precision still
1.0 and no false positives on the four clean cases. The two new detections come from one existing
Ruff rule (`SIM115`) and one new DevPilot rule (`DP001`). Combined mode stays equal to
analyzers-only; the local model still adds nothing.

Caveat up front: both rules were chosen after seeing which defects this dataset's analyzers missed.
The 9/13 is therefore optimistic. The evidence that they generalize comes from the real-code scan
below, not from this benchmark.

## Why each missed defect was missed

| Defect (seeded) | Type | Why Ruff/Bandit missed it | Decision |
|---|---|---|---|
| `qty > THRESHOLD`, docstring says "or more" | Logic / boundary | Needs the intent stated in English; `>` is valid code | Not catchable without memorizing the case (e.g. matching the docstring phrase) |
| `len(items) // size` used as page count | Logic / boundary | Floor division is usually correct | A rule would be noisy or tailored to this case |
| `xs[len(xs)]` | Bug: always raises `IndexError` | No Ruff or Bandit rule exists for it | **Implemented as DP001** |
| `f = open(...)` never closed | Resource leak | Ruff has `SIM115` but it was not selected | **Enabled `SIM115`** |
| `conn = connect(p)` not closed if `execute` raises | Resource leak | `connect` is a project-defined function; spotting the leak means tracking `conn` across lines and exception paths | Not implemented: guessing from names would be unreliable |
| `or` changed to `and` in a permission check | Logic regression | Both are valid code; the bug is in the intent | Not catchable statically |

No rule references case IDs, file paths, line numbers or the dataset's text.

## What was implemented

### 1. Ruff `SIM115` (configuration change)

`backend/app/analyzers/python_tools.py`: `RUFF_SELECT` gains `SIM115` ("use a context manager for
opening files"), mapped to category `resource`. Severity follows the existing mapping: `low`.

### 2. DevPilot rule DP001 `index-equals-length` (new analyzer)

`backend/app/analyzers/ast_rules.py`, class `AstRulesAnalyzer` (name `devpilot-ast`, version
`1.0`), registered in `default_analyzers()`.

How it works:
- Parse the file with Python's `ast`; nothing from the repository is imported or run.
- Walk every subscript that is **read**, such as `a[i]`, but not one being assigned to.
- Flag it when the index is `len(X)`, `len(X) + k` or `k + len(X)` with an integer constant k >= 0,
  and X is **the same** plain name or attribute chain as the subscripted object (`xs`,
  `self.items`), compared by syntax-tree equality.
- Report severity `high`, category `bug`, the exact line range, and the source as evidence.

For a list, tuple or string the largest valid index is `len(X) - 1`, so these reads always fail.

**Deliberately not flagged,** to keep false positives near zero:
- assignments (`d[len(d)] = x` is a common auto-increment idiom for int-keyed dicts);
- different objects (`xs[len(ys)]`);
- calls (`get()[len(get())]`, which may return different objects);
- slices (`xs[len(xs):]`, which is legal);
- any other arithmetic.

The documented limitation: an int-keyed mapping or a custom `__getitem__` could accept the read.

Why a custom rule rather than another tool: no installed tool (Ruff with all rules, Bandit) flags it.
Adding Pylint or Semgrep would add a dependency, and runtime, for a single check.

**Tests:** `backend/tests/test_ast_rules.py` (10 tests):
- positive cases: plain name, attribute chain, `+ k` on either side;
- negative cases: `len - 1`, different sequences, assignment, slice, calls, other arithmetic;
- unparseable input is skipped;
- the normalized finding has the right fields, and `SIM115` maps to `resource`;
- the analyzer is registered by default;
- realistic safe code: `lines[len(lines) - 1]`, `for i in range(len(xs))`, `xs[len(xs) // 2]`, a slice, and
  the dict append idiom are not flagged; realistic bugs (`self.items[len(self.items)]`,
  `lines[len(lines)]`) are, in source order;
- known limitations are pinned by tests: an int-keyed dict read is flagged; SIM115 fires on
  `open()` followed by `with fp:` and on manual `try/finally: close()`, and carries the caveat text.

## False-positive check on real code (not part of the benchmark)

Reproducible: `evaluation/scripts/scan_real_code.py`. Output: `realcode-scan/scan.json` and
`realcode-scan/scan.md` (generated, run 2026-10-17T18:02:42Z), plus `realcode-scan/classification.md`
(my manual reading of every hit, kept separate from the generated files).

| Rule | Corpus | Hits | Manual review |
|---|---|---|---|
| DP001 | 4,891 files, 1,203,805 lines: all installed backend dependencies plus DevPilot's `app/` | **0** | Nothing to review |
| SIM115 (Ruff 0.17.1) | 3,097 files, 588,737 lines: SQLAlchemy, Pydantic, httpx, Anthropic SDK, FastAPI, Starlette, Alembic, Bandit, email-validator, uvicorn, pytest | **10** | All 10 read. **9 deliberate** (closed by a `with` a few lines later, kept open for an object's or session's lifetime, or registered for cleanup elsewhere). **1 arguably real but minor**: `bandit/core/config.py:40` leaks the file on one error path (raises before reaching `with f:`). |

An earlier draft of this report said none of the SIM115 hits was a real leak; that was based on
reading 6 of the 10 and is corrected here.

**What this scan establishes:** on about 1.2M lines of mature library code DP001 produced no false
positives, and SIM115's useful-hit rate was about 1 in 10. **What it does not establish:** recall
on real bugs (the corpus has no labelled defects), behavior on beginner or in-progress code (where
both rules are aimed), or behavior on code unlike these libraries. It is independent of how the
rules were chosen, but it only measures false-positive noise.

SIM115 was kept because it catches a common mistake, is rated `low`, and diff/PR reviews only report
changed lines. Since this check, each SIM115 finding carries a rule-specific limitation note ("also
fires when the file is closed later... check whether it can leak") so reviewers see the caveat.

Runtime: in the scan, DP001 parsed 4,891 files in 11.5 s (about 2 ms per file). On the benchmark,
analyzer-only runs took 1.06 s p50 versus about 1.0 s before.

## Benchmark (corrected, label-blind harness; dataset, scoring, prompts and model unchanged)

Command (from `backend/`):

```bash
DEVPILOT_EVAL_OUT=../evaluation/reports/experiments/label-blind-static-v2 \
  bash ../evaluation/scripts/run_label_blind.sh static combined-single-1 combined-single-2 combined-single-3 combined-two-1
```

AI-only was not re-run: that configuration runs no analyzers, so these changes cannot affect it.
Combined two-step ran once, because three earlier repetitions showed no variation.

| Run | Detected / 13 | Recall | Precision | FP on clean | Severity match | Model calls | Failures | Model findings returned / accepted / rejected | Dup removed | p50 latency | Tokens in / out |
|---|---|---|---|---|---|---|---|---|---|---|---|
| static (before, `label-blind/static`) | 7 | 0.538 | 1.0 | 0/4 | 0.714 | 0 | 0 | — | 0 | ~1.0 s | — |
| **static (after)** | **9** | **0.692** | 1.0 | 0/4 | 0.778 | 0 | 0 | — | 0 | 1.06 s | — |
| combined-single-1 | 9 | 0.692 | 1.0 | 0/4 | 0.778 | 17 | 0 | 2 / 2 / 0 | 2 | 2.98 s | 473 / 76 |
| combined-single-2 | 9 | 0.692 | 1.0 | 0/4 | 0.778 | 17 | 0 | 2 / 2 / 0 | 2 | 3.28 s | 473 / 76 |
| combined-single-3 | 9 | 0.692 | 1.0 | 0/4 | 0.778 | 17 | 0 | 2 / 2 / 0 | 2 | 2.98 s | 473 / 76 |
| combined-two-1 | 9 | 0.692 | 1.0 | 0/4 | 0.778 | 33 | 1 (HTTP 500, repeat limit) | 1 / 1 / 0 | 1 | 14.1 s | 1,312 / 394 |

- **Newly detected:** `boundary-last-index` (DP001, line 6, severity high, matching the reference)
  and `resource-file-not-closed` (SIM115, line 7, severity low, matching the reference).
- **Still missed:** `boundary-discount-threshold`, `boundary-pagination-drops-last-page`,
  `logic-inverted-permission`, `resource-connection-leak-on-error`.
- **Regressions:** none. The 7 earlier detections are all still found, and no new false positive
  appeared on clean or defective cases. The model's findings in combined mode were all removed as
  duplicates of analyzer findings, as before.

## Limitations

- The rules were selected with knowledge of the missed defects in this dataset. A held-out set of
  new cases is needed to estimate real recall.
- 13 defects is a very small sample; one detection moves recall by about 0.08.
- SIM115 produced mostly false positives on mature library code (9 of 10 hits deliberate; see above).
- There is no independent labelled test set yet (see "Independent validation" below).
- DP001 found nothing in 1.2M lines of mature code, so its practical value is mainly catching
  fresh mistakes in diffs, not finding bugs in established projects.
- The remaining four defects need intent or data-flow reasoning; that is where a stronger model,
  or proper data-flow analysis, would have to contribute.

## Independent validation

The repository has no independent corpus with labelled defects: dataset v1 was used to choose the
rules, and `fixtures/sample_repositories/inventory_service` shares the same seeded defects and author.
The real-code scan measures only false positives. Proposed plan, kept separate from v1:

1. **Held-out synthetic set (`evaluation/datasets/v2-holdout/`).** At least 20 new before/after
   cases written by someone who has not read DP001's code (you, or a friend), across the same six
   categories plus clean changes (at least 5 clean). Freeze it before running anything; score it
   once per configuration.
2. **Real bug fixes from permissively licensed projects.** Pick 15–20 public bug-fix commits
   (Python, small diffs), record repository, commit, license and the defective lines from the fix,
   and review the parent commit. This needs your approval because it downloads public code; it
   uses no paid service and uploads nothing.
3. **Report separately** from v1, with the rules frozen at their current version (`devpilot-ast`
   1.0, Ruff 0.17.1 with the current `RUFF_SELECT`).

## How to explain this in an interview

"The benchmark showed six defects the analyzers missed. I classified each by why it was missed.
Four needed intent or cross-line data flow, so any cheap rule would either be noisy or would just
memorize my test cases. Two were mechanical. One was already covered by a Ruff rule we hadn't
enabled. The other, indexing a sequence by its own length, had no existing rule, so I wrote a
small syntax-tree check that only fires on the exact always-wrong shape. Before claiming
anything, I ran both rules over about a million lines of real library code. The custom rule had
zero hits; the Ruff rule had ten, and when I read all ten, nine were deliberate patterns and one
was a minor real leak on an error path. I kept it, but documented that cost and attached a caveat to
every finding it produces. Recall went from 7 to 9 out of 13 with no new false positives. I report that
as optimistic, because I chose the rules after seeing the misses."
