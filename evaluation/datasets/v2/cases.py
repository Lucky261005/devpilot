"""DevPilot evaluation dataset v2 (held out).

Written on 2026-10-23, after every analyzer rule and before any prompt or context change of
Phase 3, and never used to tune them. It is still SYNTHETIC and written by the same team that
built the tool, so it is weaker evidence than real-world bugs: treat results as indicative.

What v2 adds over v1:
- multi-file cases: the defect is in the changed file, but proving it needs a definition
  from another, unchanged file (a unit, an argument order, a None return, a raised error);
- realistic single-file bugs (retry count, naive vs aware datetimes, mutation while
  iterating, empty input), security issues, and clean changes designed to tempt false
  positives (including a correct multi-file call).

Format as in v1: `before` is committed first, then `after`; the review covers that diff.
Files only in `before` stay in the repository unchanged. `expected` locates defects on the
AFTER version (lines are 1-based, inclusive).
"""

from textwrap import dedent as d

_TAX = d('''\
    def apply_tax(amount, rate):
        """Return amount with tax added. rate is a fraction, e.g. 0.2 for 20%."""
        return round(amount * (1 + rate), 2)
    ''')

CASES = [
    # ---------------------------------------------------------------- multi-file
    {
        "id": "mf-timeout-units",
        "label": "synthetic-multifile",
        "before": {
            "net/__init__.py": "",
            "net/client.py": d('''\
                import urllib.request


                def fetch(url, timeout_s):
                    """Fetch a URL. timeout_s is in seconds."""
                    with urllib.request.urlopen(url, timeout=timeout_s) as r:  # noqa: S310
                        return r.read()
                '''),
        },
        "after": {"jobs.py": d('''\
            from net.client import fetch

            HEALTH_URL = "https://status.example.com/health"


            def check_health():
                # Give the status page 5 seconds before treating it as down.
                return fetch(HEALTH_URL, 5000)
            ''')},
        "expected": [{"path": "jobs.py", "lines": [8, 8], "category": "logic", "severity": "medium",
                      "description": "fetch takes seconds; 5000 means an 83-minute timeout, not 5 s.",
                      "rationale": "A hung status page blocks the health check for over an hour."}],
    },
    {
        "id": "mf-none-return-unchecked",
        "label": "synthetic-multifile",
        "before": {
            "users/__init__.py": "",
            "users/repo.py": d('''\
                def find_user(db, user_id):
                    """Return the user row as a dict, or None when no user has this id."""
                    row = db.get("users", user_id)
                    return dict(row) if row else None
                '''),
        },
        "after": {"profile.py": d('''\
            from users.repo import find_user


            def display_name(db, user_id):
                user = find_user(db, user_id)
                return user["first"] + " " + user["last"]
            ''')},
        "expected": [{"path": "profile.py", "lines": [5, 6], "category": "bug", "severity": "medium",
                      "description": "find_user returns None for unknown ids; subscripting it raises TypeError.",
                      "rationale": "Any request for a deleted or unknown user becomes a 500."}],
    },
    {
        "id": "mf-swapped-arguments",
        "label": "synthetic-multifile",
        "before": {"billing/__init__.py": "", "billing/tax.py": _TAX},
        "after": {"billing/invoice.py": d('''\
            from billing.tax import apply_tax

            VAT = 0.2


            def invoice_total(subtotal):
                return apply_tax(VAT, subtotal)
            ''')},
        "expected": [{"path": "billing/invoice.py", "lines": [7, 7], "category": "bug", "severity": "high",
                      "description": "Arguments swapped: apply_tax(amount, rate) is called as (rate, amount).",
                      "rationale": "Every invoice total is wrong (0.2 * (1 + subtotal))."}],
    },
    {
        "id": "mf-unhandled-keyerror",
        "label": "synthetic-multifile",
        "before": {
            "config/__init__.py": "",
            "config/settings.py": d('''\
                _SETTINGS = {"dark_mode": "on"}


                def get_setting(name):
                    """Return a configured value. Raises KeyError if name is not configured."""
                    return _SETTINGS[name]
                '''),
        },
        "after": {"features.py": d('''\
            from config.settings import get_setting


            def feature_enabled(flag):
                # Missing flags count as disabled.
                return get_setting(flag) == "on"
            ''')},
        "expected": [{"path": "features.py", "lines": [5, 6], "category": "error_handling", "severity": "medium",
                      "description": "get_setting raises KeyError for unknown flags; the comment promises False.",
                      "rationale": "Checking any new, unconfigured flag crashes instead of disabling it."}],
    },
    # ---------------------------------------------------------------- realistic single-file
    {
        "id": "rw-retry-count-off-by-one",
        "label": "synthetic",
        "before": {"retry.py": "import time\n"},
        "after": {"retry.py": d('''\
            import time


            def with_retries(fn, attempts=3):
                """Call fn, retrying up to `attempts` times in total."""
                for i in range(1, attempts):
                    try:
                        return fn()
                    except ConnectionError:
                        time.sleep(2**i)
                raise RuntimeError("all attempts failed")
            ''')},
        "expected": [{"path": "retry.py", "lines": [6, 6], "category": "logic", "severity": "medium",
                      "description": "range(1, attempts) makes attempts - 1 calls, not attempts.",
                      "rationale": "One fewer try than documented; attempts=1 never calls fn at all."}],
    },
    {
        "id": "rw-naive-vs-aware-datetime",
        "label": "synthetic",
        "before": {"tokens.py": "from datetime import datetime\n\nNEVER = None\n"},
        "after": {"tokens.py": d('''\
            from datetime import datetime

            NEVER = None


            def is_expired(expires_at):
                """expires_at is a timezone-aware UTC datetime from the database."""
                return expires_at < datetime.now()
            ''')},
        "expected": [{"path": "tokens.py", "lines": [8, 8], "category": "bug", "severity": "high",
                      "description": "Comparing an aware datetime with naive datetime.now() raises TypeError.",
                      "rationale": "Every expiry check crashes; use datetime.now(timezone.utc)."}],
    },
    {
        "id": "rw-delete-while-iterating",
        "label": "synthetic",
        "before": {"sessions.py": "SESSIONS = {}\n"},
        "after": {"sessions.py": d('''\
            SESSIONS = {}


            def drop_expired(sessions, now):
                for sid, sess in sessions.items():
                    if sess["expires"] < now:
                        del sessions[sid]
                return sessions
            ''')},
        "expected": [{"path": "sessions.py", "lines": [5, 7], "category": "bug", "severity": "medium",
                      "description": "Deleting from a dict while iterating it raises RuntimeError.",
                      "rationale": "Cleanup fails as soon as one session has expired."}],
    },
    {
        "id": "rw-average-of-empty",
        "label": "synthetic",
        "before": {"metrics.py": "UNIT = 'ms'\n"},
        "after": {"metrics.py": d('''\
            UNIT = 'ms'


            def average_latency(samples):
                """Mean of the samples in ms; 0.0 when there are none."""
                return sum(samples) / len(samples)
            ''')},
        "expected": [{"path": "metrics.py", "lines": [6, 6], "category": "bug", "severity": "low",
                      "description": "Empty samples raise ZeroDivisionError; the docstring promises 0.0.",
                      "rationale": "Dashboards with no traffic in a window crash."}],
    },
    # ---------------------------------------------------------------- security
    {
        "id": "sec-path-traversal",
        "label": "synthetic",
        "before": {"files.py": "import os\n\nUPLOAD_DIR = \"/srv/uploads\"\n"},
        "after": {"files.py": d('''\
            import os

            UPLOAD_DIR = "/srv/uploads"


            def read_upload(filename):
                path = os.path.join(UPLOAD_DIR, filename)
                with open(path, "rb") as f:
                    return f.read()
            ''')},
        "expected": [{"path": "files.py", "lines": [7, 8], "category": "security", "severity": "high",
                      "description": "User-supplied filename joined unchecked: '../' or an absolute path escapes UPLOAD_DIR.",
                      "rationale": "Arbitrary file read on the server."}],
    },
    {
        "id": "sec-pickle-from-cookie",
        "label": "synthetic",
        "before": {"session_store.py": "import pickle\n"},
        "after": {"session_store.py": d('''\
            import pickle


            def load_session(cookie_value: bytes):
                return pickle.loads(cookie_value)
            ''')},
        "expected": [{"path": "session_store.py", "lines": [5, 5], "category": "security", "severity": "critical",
                      "description": "Unpickling client-controlled data allows arbitrary code execution.",
                      "rationale": "Any visitor can run code on the server."}],
    },
    {
        "id": "sec-jwt-signature-ignored",
        "label": "synthetic",
        "before": {"auth.py": "import jwt\n"},
        "after": {"auth.py": d('''\
            import jwt


            def current_user_id(token):
                claims = jwt.decode(token, options={"verify_signature": False})
                return claims["sub"]
            ''')},
        "expected": [{"path": "auth.py", "lines": [5, 6], "category": "security", "severity": "critical",
                      "description": "JWT signature verification is disabled, so anyone can forge a token.",
                      "rationale": "Authentication bypass: impersonate any user by editing 'sub'."}],
    },
    {
        "id": "rw-default-arg-evaluated-once",
        "label": "synthetic",
        "before": {"audit.py": "from datetime import datetime, timezone\n"},
        "after": {"audit.py": d('''\
            from datetime import datetime, timezone


            def record(event, at=datetime.now(timezone.utc)):
                return {"event": event, "at": at.isoformat()}
            ''')},
        "expected": [{"path": "audit.py", "lines": [4, 4], "category": "bug", "severity": "medium",
                      "description": "The default timestamp is computed once at import, so every record gets the same time.",
                      "rationale": "Audit records carry the server start time, not the event time."}],
    },
    # ---------------------------------------------------------------- clean (false-positive traps)
    {
        "id": "clean-parameterized-sql",
        "label": "synthetic",
        "before": {"orders.py": "TABLE = 'orders'\n"},
        "after": {"orders.py": d('''\
            TABLE = 'orders'


            def find_orders(conn, customer_id):
                cur = conn.execute("SELECT id, total FROM orders WHERE customer = ?", (customer_id,))
                return cur.fetchall()
            ''')},
        "expected": [],
    },
    {
        "id": "clean-log-and-reraise",
        "label": "synthetic",
        "before": {"payments.py": "import logging\n\nlog = logging.getLogger(__name__)\n"},
        "after": {"payments.py": d('''\
            import logging

            log = logging.getLogger(__name__)


            def charge(gateway, amount):
                try:
                    return gateway.charge(amount)
                except Exception:
                    log.exception("charge failed")
                    raise
            ''')},
        "expected": [],
    },
    {
        "id": "clean-guarded-division",
        "label": "synthetic",
        "before": {"stats.py": "PRECISION = 3\n"},
        "after": {"stats.py": d('''\
            PRECISION = 3


            def hit_ratio(hits, total):
                """Share of requests served from cache; 0.0 when there were none."""
                if total == 0:
                    return 0.0
                return round(hits / total, PRECISION)
            ''')},
        "expected": [],
    },
    {
        "id": "clean-multifile-correct-call",
        "label": "synthetic-multifile",
        "before": {"billing/__init__.py": "", "billing/tax.py": _TAX},
        "after": {"billing/receipt.py": d('''\
            from billing.tax import apply_tax

            VAT = 0.2


            def receipt_total(subtotal):
                return apply_tax(subtotal, VAT)
            ''')},
        "expected": [],
    },
    {
        "id": "clean-multifile-none-handled",
        "label": "synthetic-multifile",
        "before": {
            "users/__init__.py": "",
            "users/repo.py": d('''\
                def find_user(db, user_id):
                    """Return the user row as a dict, or None when no user has this id."""
                    row = db.get("users", user_id)
                    return dict(row) if row else None
                '''),
        },
        "after": {"greeting.py": d('''\
            from users.repo import find_user


            def greeting(db, user_id):
                user = find_user(db, user_id)
                if user is None:
                    return "Hello, guest"
                return "Hello, " + user["first"]
            ''')},
        "expected": [],
    },
]
