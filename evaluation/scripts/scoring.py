"""Matching and metric helpers for run_eval.py (kept import-free so they are unit-testable)."""

import hashlib

TOLERANCE = 2  # lines of slack when matching a prediction to a reference defect


def score(preds: list[dict], expected: list[dict]) -> dict:
    matched: set[int] = set()
    tp = fp = dup = sev_ok = 0
    for p in preds:
        hit = None
        for i, e in enumerate(expected):
            es, ee = e["lines"]
            if p["path"] == e["path"] and p["start_line"] - TOLERANCE <= ee and es <= p["end_line"] + TOLERANCE:
                hit = i
                break
        if hit is None:
            fp += 1
        elif hit in matched:
            dup += 1
        else:
            matched.add(hit)
            tp += 1
            sev_ok += p["severity"] == expected[hit]["severity"]
    return {
        "tp": tp,
        "fp": fp,
        "fn": len(expected) - len(matched),
        "duplicates": dup,
        "severity_exact": sev_ok,
        "matched_ids": sorted(matched),
    }


def pct(n: float, d: float) -> float | None:
    return round(n / d, 3) if d else None


def percentile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def opaque_repo_name(case_id: str) -> str:
    """Name for a case's throwaway repository. The repository name is shown to the model, so it
    must not reveal the case ID, defect type or whether the case is clean. It depends only on the
    case ID (so scoring can map results back and every configuration sees the same prompt) and is
    a one-way hash of it."""
    return "repo-" + hashlib.sha256(f"devpilot-eval:{case_id}".encode()).hexdigest()[:8]
