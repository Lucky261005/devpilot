# Demonstration script (about 5 minutes)

All data in this demo is **sample data** from `fixtures/sample_repositories/inventory_service`,
a tiny package with deliberately seeded defects (listed in its `SEEDED_DEFECTS.md`).

## Setup (once)

```bash
# backend/.env must allow the parent directory of the demo repo, e.g.
#   DEVPILOT_ALLOWED_LOCAL_ROOTS=/path/to/projects
python scripts/make_demo_repo.py ../devpilot-demo-repo
cd backend && uv run alembic upgrade head && uv run uvicorn app.main:app --port 8000
cd frontend && npm run dev
```

Open http://localhost:5173 and create an account (any email and a 10+ character password; it
stays in your local database).

## Script

1. **Import.** Add repository → *Local Git path* → name `inventory-demo`, path to
   `devpilot-demo-repo`. Point out the index summary (file count, skipped files) and that the LLM
   checkbox is off by default and explains what would be sent.
2. **Whole-repository review.** Select *Whole repository* → Start review. The page shows
   queued → running (with stage) → completed. Three analyzer findings appear, most severe first:
   - Bandit **B602** `shell=True` (high) at `inventory/store.py:27`,
   - Ruff **E722** bare `except` (medium) at line 17,
   - Bandit **B105** hardcoded password (low) at line 7.
   Click B602: the source opens with line 27 highlighted, plus rule docs and the rule's
   limitation. Mark it *Useful*.
3. **Filters.** Toggle *high* and *security* chips to show filtering.
4. **Change review.** Back on the repository, keep *Compare two refs* (`HEAD~1`..`HEAD`) and
   start. The change only touches `pricing.py`. Result: **no findings** — the two seeded bugs
   there (`>` instead of `>=`, a dropped last page) are logic errors no analyzer can see. Open
   *Changed files* for the diff, and *Test suggestions* for the generated pytest skeletons for
   `apply_discount` and `paginate`.
   This is the honest motivation for the LLM stage.
5. **LLM stage (only with `ANTHROPIC_API_KEY` set).** Tick *Allow LLM review*, start the same
   change review with *Include LLM review*. The run summary shows model, tokens, latency and how
   many model findings passed validation; model findings carry the *LLM hypothesis* badge.
   Without a key, the run summary says the LLM stage was skipped and why.
6. **Search.** Search tab → *Definition* mode → `apply_discount` → click the hit to open the file.
7. **Settings.** Show the data-flow disclosure, limits and retention.
8. **Evaluation.** `cd backend && uv run python ../evaluation/scripts/run_eval.py --configs static`
   and open `evaluation/reports/latest.md`. Explain that LLM configurations are reported as
   "not run" unless a key is present.

## Reset

Delete the repository from its page (removes all reviews and snapshots), or stop the servers and
delete `backend/devpilot.db` and `backend/data/`.
