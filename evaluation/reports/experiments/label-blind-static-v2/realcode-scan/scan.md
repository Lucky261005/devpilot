# Real-code false-positive scan (2026-10-17T18:02:42Z)

Not a recall measurement: the corpus has no labelled bugs.

- DP001 v1.0: 4,891 files, 1,203,805 lines, **0 hits** (11.5 s)
- SIM115 (Ruff 0.17.1): 3,097 files, 588,737 lines, **10 hits**

Packages scanned for SIM115: sqlalchemy 2.1.5, pydantic 2.14.1, httpx 0.28.1, anthropic 1.15.0, fastapi 0.143.3, starlette 1.8.0, alembic 1.20.0, bandit 1.9.4, email_validator 2.3.0, uvicorn 0.54.0, _pytest 9.1.1

## SIM115 hits

- `_pytest/assertion/rewrite.py:362`
- `_pytest/capture.py:489`
- `_pytest/capture.py:493`
- `_pytest/config/__init__.py:505`
- `_pytest/helpconfig.py:129`
- `_pytest/pastebin.py:47`
- `bandit/core/config.py:40`
- `bandit/formatters/xml.py:91`
- `sqlalchemy/testing/profiles_file.py:242`
- `starlette/formparsers.py:234`

## DP001 hits

(none)
