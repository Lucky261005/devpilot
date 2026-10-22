# Manual classification of the SIM115 hits in `scan.md`

Read by hand on 2026-10-17 from the installed package sources (versions listed in `scan.json`).
This file is a human judgement, kept separate from the generated `scan.md` / `scan.json`.

| Hit | What the code does | Verdict |
|---|---|---|
| `_pytest/assertion/rewrite.py:362` | `fp = open(...)` inside `try`; on success the next statement is `with fp:` | Deliberate; closed |
| `_pytest/capture.py:489` | `self.tmpfile = open(os.devnull)` kept for the capture object's lifetime | Deliberate |
| `_pytest/capture.py:493` | `TemporaryFile` wrapped and kept for the capture object's lifetime | Deliberate |
| `_pytest/config/__init__.py:505` | Re-opens a duplicated stderr file descriptor for the process lifetime | Deliberate |
| `_pytest/helpconfig.py:129` | `--debug` log file kept open for the session and closed in a cleanup hook | Deliberate |
| `_pytest/pastebin.py:47` | `TemporaryFile` stored in the config stash for the session | Deliberate |
| `bandit/core/config.py:40` | `f = open(...)`, later `with f:`; but if the TOML parser is missing it raises **before** the `with`, leaving `f` open on that error path | **Arguably a real, minor leak (error path only)** |
| `bandit/formatters/xml.py:91` | Re-opens the output file; the next block is `with fileobj:` | Deliberate; closed |
| `sqlalchemy/testing/profiles_file.py:242` | `open(...)` inside `try`; then `with profile_f:` | Deliberate; closed |
| `starlette/formparsers.py:234` | `SpooledTemporaryFile` appended to `_files_to_close_on_error` and handed to `UploadFile` | Deliberate; lifetime managed elsewhere |

**Summary:** 10 hits; 9 deliberate (would be "not actionable" in a review); 1 arguably real but minor
(leak on one error path). On this mature-library corpus, SIM115's useful-hit rate was about 1 in 10.

DP001 had no hits, so there was nothing to classify.
