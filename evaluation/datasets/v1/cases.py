"""DevPilot evaluation dataset v1.

Every case is SYNTHETIC: small code changes written for this benchmark, with defects seeded
deliberately. No case is taken from a real project, so results say nothing definitive about
performance on production repositories. Each case is a before/after pair; the review covers
the diff between them.

Labels: `expected` lists the defects a reviewer should report, located on the AFTER version.
A clean case (expected == []) is a change with no actionable defect; any finding there is a
false positive.

Fields per expected defect:
  path, lines (start, end on the new side), category, severity, description, rationale
"""

from textwrap import dedent as d

CASES = [
    # ---------------------------------------------------------------- boundary / conditions
    {
        "id": "boundary-discount-threshold",
        "label": "synthetic",
        "before": {"shop/pricing.py": d('''\
            THRESHOLD = 100


            def total(price, qty):
                return price * qty
            ''')},
        "after": {"shop/pricing.py": d('''\
            THRESHOLD = 100


            def total(price, qty):
                """Orders of THRESHOLD units or more get 10% off."""
                if qty > THRESHOLD:
                    return price * qty * 0.9
                return price * qty
            ''')},
        "expected": [{"path": "shop/pricing.py", "lines": [6, 6], "category": "logic", "severity": "medium",
                      "description": "`>` excludes exactly THRESHOLD units; docstring says 'or more'.",
                      "rationale": "Customers ordering exactly 100 are overcharged; money-affecting but bounded."}],
    },
    {
        "id": "boundary-pagination-drops-last-page",
        "label": "synthetic",
        "before": {"util/pages.py": "def first(items):\n    return items[:1]\n"},
        "after": {"util/pages.py": d('''\
            def first(items):
                return items[:1]


            def paginate(items, size):
                pages = len(items) // size
                return [items[i * size:(i + 1) * size] for i in range(pages)]
            ''')},
        "expected": [{"path": "util/pages.py", "lines": [6, 7], "category": "logic", "severity": "medium",
                      "description": "Floor division drops the final partial page.",
                      "rationale": "Silent data loss in listings whenever len % size != 0."}],
    },
    {
        "id": "boundary-last-index",
        "label": "synthetic",
        "before": {"util/seq.py": "def head(xs):\n    return xs[0]\n"},
        "after": {"util/seq.py": d('''\
            def head(xs):
                return xs[0]


            def last(xs):
                return xs[len(xs)]
            ''')},
        "expected": [{"path": "util/seq.py", "lines": [6, 6], "category": "bug", "severity": "high",
                      "description": "xs[len(xs)] always raises IndexError.",
                      "rationale": "Function can never succeed."}],
    },
    # ---------------------------------------------------------------- error handling
    {
        "id": "errors-bare-except-swallows",
        "label": "synthetic",
        "before": {"app/config.py": "import json\n\n\ndef load(path):\n    with open(path) as f:\n        return json.load(f)\n"},
        "after": {"app/config.py": d('''\
            import json


            def load(path):
                try:
                    with open(path) as f:
                        return json.load(f)
                except:
                    return {}
            ''')},
        "expected": [{"path": "app/config.py", "lines": [8, 9], "category": "error_handling", "severity": "medium",
                      "description": "Bare except hides malformed config and even KeyboardInterrupt.",
                      "rationale": "Misconfiguration silently becomes empty config."}],
    },
    {
        "id": "errors-lost-exception-context",
        "label": "synthetic",
        "before": {"app/fetch.py": "def parse(s):\n    return int(s)\n"},
        "after": {"app/fetch.py": d('''\
            class ParseError(Exception):
                pass


            def parse(s):
                try:
                    return int(s)
                except ValueError:
                    raise ParseError("bad number")
            ''')},
        "expected": [{"path": "app/fetch.py", "lines": [9, 9], "category": "error_handling", "severity": "low",
                      "description": "Re-raise without `from` loses the original exception chain.",
                      "rationale": "Debuggability issue only; behavior otherwise correct."}],
    },
    # ---------------------------------------------------------------- resources
    {
        "id": "resource-file-not-closed",
        "label": "synthetic",
        "before": {"io_utils.py": "def size(path):\n    import os\n    return os.path.getsize(path)\n"},
        "after": {"io_utils.py": d('''\
            def size(path):
                import os
                return os.path.getsize(path)


            def read_header(path):
                f = open(path, "rb")
                return f.read(16)
            ''')},
        "expected": [{"path": "io_utils.py", "lines": [7, 8], "category": "resource", "severity": "low",
                      "description": "File handle is never closed.",
                      "rationale": "Leaks descriptors under load; CPython usually collects it."}],
    },
    {
        "id": "resource-connection-leak-on-error",
        "label": "synthetic",
        "before": {"db.py": "import sqlite3\n\n\ndef connect(p):\n    return sqlite3.connect(p)\n"},
        "after": {"db.py": d('''\
            import sqlite3


            def connect(p):
                return sqlite3.connect(p)


            def count_users(p):
                conn = connect(p)
                n = conn.execute("select count(*) from users").fetchone()[0]
                conn.close()
                return n
            ''')},
        "expected": [{"path": "db.py", "lines": [9, 11], "category": "resource", "severity": "low",
                      "description": "Connection is not closed if the query raises.",
                      "rationale": "Use try/finally or a context manager."}],
    },
    # ---------------------------------------------------------------- logic regressions
    {
        "id": "logic-inverted-permission",
        "label": "synthetic",
        "before": {"auth/perm.py": d('''\
            def can_edit(user, doc):
                return user.is_admin or doc.owner_id == user.id
            ''')},
        "after": {"auth/perm.py": d('''\
            def can_edit(user, doc):
                if user.is_banned:
                    return False
                return user.is_admin and doc.owner_id == user.id
            ''')},
        "expected": [{"path": "auth/perm.py", "lines": [4, 4], "category": "security", "severity": "high",
                      "description": "`or` became `and`: owners who are not admins lose edit access.",
                      "rationale": "Authorization regression unrelated to the stated banned-user change."}],
    },
    {
        "id": "logic-mutable-default",
        "label": "synthetic",
        "before": {"cart.py": "def new_cart():\n    return []\n"},
        "after": {"cart.py": d('''\
            def new_cart():
                return []


            def add_item(item, cart=[]):
                cart.append(item)
                return cart
            ''')},
        "expected": [{"path": "cart.py", "lines": [5, 7], "category": "bug", "severity": "medium",
                      "description": "Mutable default list is shared between calls.",
                      "rationale": "Items leak across carts/users."}],
    },
    # ---------------------------------------------------------------- security
    {
        "id": "security-shell-injection",
        "label": "synthetic",
        "before": {"tools/report.py": "import subprocess\n\n\ndef version():\n    return subprocess.check_output(['git', '--version'])\n"},
        "after": {"tools/report.py": d('''\
            import subprocess


            def version():
                return subprocess.check_output(['git', '--version'])


            def archive(branch):
                return subprocess.call("git archive " + branch, shell=True)
            ''')},
        "expected": [{"path": "tools/report.py", "lines": [9, 9], "category": "security", "severity": "high",
                      "description": "User-controlled branch name reaches a shell.",
                      "rationale": "Command injection if branch is attacker-controlled."}],
    },
    {
        "id": "security-sql-fstring",
        "label": "synthetic",
        "before": {"repo/users.py": "def all_users(conn):\n    return conn.execute('select * from users').fetchall()\n"},
        "after": {"repo/users.py": d('''\
            def all_users(conn):
                return conn.execute('select * from users').fetchall()


            def by_name(conn, name):
                return conn.execute(f"select * from users where name = '{name}'").fetchall()
            ''')},
        "expected": [{"path": "repo/users.py", "lines": [6, 6], "category": "security", "severity": "high",
                      "description": "SQL built with an f-string from a parameter.",
                      "rationale": "SQL injection; use parameter binding."}],
    },
    {
        "id": "security-yaml-load",
        "label": "synthetic",
        "before": {"cfg.py": "import json\n\n\ndef parse(s):\n    return json.loads(s)\n"},
        "after": {"cfg.py": d('''\
            import json

            import yaml


            def parse(s):
                return json.loads(s)


            def parse_yaml(s):
                return yaml.load(s, Loader=yaml.Loader)
            ''')},
        "expected": [{"path": "cfg.py", "lines": [11, 11], "category": "security", "severity": "medium",
                      "description": "yaml.Loader can construct arbitrary Python objects.",
                      "rationale": "Use yaml.safe_load for untrusted input."}],
    },
    {
        "id": "security-tls-verify-off",
        "label": "synthetic",
        "before": {"client.py": "import requests\n\n\ndef ping(url):\n    return requests.get(url, timeout=5).ok\n"},
        "after": {"client.py": d('''\
            import requests


            def ping(url):
                return requests.get(url, timeout=5, verify=False).ok
            ''')},
        "expected": [{"path": "client.py", "lines": [5, 5], "category": "security", "severity": "high",
                      "description": "TLS certificate verification disabled.",
                      "rationale": "Enables man-in-the-middle attacks."}],
    },
    # ---------------------------------------------------------------- clean changes
    {
        "id": "clean-rename-variable",
        "label": "synthetic-clean",
        "before": {"math_utils.py": "def mean(xs):\n    t = sum(xs)\n    return t / len(xs) if xs else 0.0\n"},
        "after": {"math_utils.py": "def mean(xs):\n    total = sum(xs)\n    return total / len(xs) if xs else 0.0\n"},
        "expected": [],
    },
    {
        "id": "clean-add-typed-helper",
        "label": "synthetic-clean",
        "before": {"text.py": "def words(s: str) -> list[str]:\n    return s.split()\n"},
        "after": {"text.py": d('''\
            def words(s: str) -> list[str]:
                return s.split()


            def count_words(s: str) -> int:
                """Number of whitespace-separated words."""
                return len(words(s))
            ''')},
        "expected": [],
    },
    {
        "id": "clean-context-manager-refactor",
        "label": "synthetic-clean",
        "before": {"files.py": "def read(p):\n    f = open(p)\n    try:\n        return f.read()\n    finally:\n        f.close()\n"},
        "after": {"files.py": "def read(p):\n    with open(p, encoding='utf-8') as f:\n        return f.read()\n"},
        "expected": [],
    },
    {
        "id": "clean-safe-subprocess",
        "label": "synthetic-clean",
        "before": {"git_tools.py": "import subprocess\n\n\ndef status():\n    return subprocess.run(['git', 'status'], capture_output=True, check=True).stdout\n"},
        "after": {"git_tools.py": d('''\
            import subprocess


            def status():
                return subprocess.run(['git', 'status'], capture_output=True, check=True).stdout


            def log(n: int):
                return subprocess.run(['git', 'log', f'-{int(n)}'], capture_output=True, check=True).stdout
            ''')},
        "expected": [],
    },
]
