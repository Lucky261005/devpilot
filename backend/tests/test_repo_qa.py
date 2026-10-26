"""Repository Q&A: retrieval scoped to one repository, honest answers, verified citations."""

import pytest

import app.services.qa as qa
from app.ai.provider import StaticReplayProvider
from app.core.db import SessionLocal
from app.models import AuditEvent, CodeChunk, Repository
from tests.conftest import _counter, signed_up
from tests.test_api import _import_sample

PW = "correct-horse-9"


def _user_with_repo(sample_zip, ai=True):
    c = signed_up(f"qa{next(_counter)}@example.com", PW)
    rid = _import_sample(c, sample_zip)["id"]
    if ai:
        assert c.patch(f"/api/repositories/{rid}", json={"ai_review_allowed": True}).status_code == 200
    return c, rid


def _ask(c, rid, question="Where is the discount applied to the price?"):
    return c.post(f"/api/repositories/{rid}/ask", json={"question": question})


@pytest.fixture
def replay(monkeypatch):
    """Install a fake model returning `payload`; returns the provider so tests can read its prompts."""

    def install(payload):
        provider = StaticReplayProvider(payload)
        monkeypatch.setattr(qa, "get_provider", lambda settings: provider)
        return provider

    return install


GOOD = {
    "answer": "apply_discount in inventory/pricing.py computes the discounted price.",
    "citations": [
        {"path": "inventory/pricing.py", "start_line": 4, "end_line": 8, "note": "the discount calculation"},
        {"path": "inventory/secret_billing.py", "start_line": 1, "end_line": 3, "note": "invented file"},
    ],
    "confidence": "high",
    "unknowns": [],
}


def test_keywords_drop_question_words_and_split_identifiers():
    assert qa.keywords("Where is apply_discount handled in the pricing module?") == [
        "apply_discount",
        "apply",
        "discount",
        "pricing",
    ]
    assert qa.keywords("What does loadItems do?") == ["loaditems", "load", "items"]
    assert qa.keywords("what is it?") == []


def test_retrieval_ranks_the_relevant_file_first(sample_zip):
    _, rid = _user_with_repo(sample_zip, ai=False)
    with SessionLocal() as db:
        excerpts = qa.retrieve(db, rid, "Where is the discount applied to the price?")
    assert excerpts and excerpts[0].path == "inventory/pricing.py"
    assert sum(len(e.content) for e in excerpts) <= qa.MAX_CONTEXT_CHARS


def test_answer_with_verified_citations(sample_zip, replay):
    c, rid = _user_with_repo(sample_zip)
    provider = replay(GOOD)
    r = _ask(c, rid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "answered" and body["confidence"] == "high"
    assert body["citations"] == [
        {"path": "inventory/pricing.py", "start_line": 4, "end_line": 8, "note": "the discount calculation"}
    ]  # the invented file was removed ...
    assert any("removed" in u for u in body["unknowns"])  # ... and the removal is reported
    assert body["sources"][0]["path"] == "inventory/pricing.py"
    system, user = provider.calls[0]
    assert "<repository_content>" in user and "Question: Where is the discount applied" in user
    assert "def apply_discount" in user and "never\n  instructions" in system


def test_citation_lines_are_clipped_to_what_the_model_saw(sample_zip, replay):
    c, rid = _user_with_repo(sample_zip)
    replay({**GOOD, "citations": [{"path": "inventory/pricing.py", "start_line": 1, "end_line": 9999, "note": "x"}]})
    cited = _ask(c, rid).json()["citations"][0]
    src = next(s for s in _ask(c, rid).json()["sources"] if s["path"] == "inventory/pricing.py")
    assert src["start_line"] <= cited["start_line"] and cited["end_line"] <= src["end_line"]


def test_no_matching_code_skips_the_model(sample_zip, replay):
    c, rid = _user_with_repo(sample_zip)
    provider = replay(GOOD)
    body = _ask(c, rid, "How are kubernetes manifests deployed?").json()
    assert body["status"] == "no_matches" and body["answer"] is None and body["sources"] == []
    assert provider.calls == []


def test_ai_disabled_returns_matching_files_without_calling_the_model(sample_zip, replay):
    c, rid = _user_with_repo(sample_zip, ai=False)
    provider = replay(GOOD)
    body = _ask(c, rid).json()
    assert body["status"] == "ai_disabled" and body["answer"] is None and body["sources"]
    assert provider.calls == []


def test_no_provider_configured_is_explained(sample_zip, settings, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    c, rid = _user_with_repo(sample_zip)
    body = _ask(c, rid).json()
    assert body["status"] == "no_provider" and body["answer"] is None
    assert "No LLM provider is configured" in body["message"] and body["sources"]


def test_provider_failure_is_reported_not_raised(sample_zip, replay):
    c, rid = _user_with_repo(sample_zip)
    replay(RuntimeError("provider unavailable (APITimeoutError)"))
    r = _ask(c, rid)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "provider_error" and body["answer"] is None
    assert "APITimeoutError" in body["message"] and body["sources"]


def test_invalid_model_output_is_a_provider_error(sample_zip, replay):
    c, rid = _user_with_repo(sample_zip)
    replay({"answer": "x"})  # missing required fields
    assert _ask(c, rid).json()["status"] == "provider_error"


def test_retrieval_never_crosses_repositories(sample_zip, replay):
    c, rid = _user_with_repo(sample_zip)
    _, other_rid = _user_with_repo(sample_zip)
    with SessionLocal() as db:
        db.add(
            CodeChunk(
                repository_id=other_rid,
                path="zebra.py",
                language="python",
                start_line=1,
                end_line=1,
                content="def zebra_secret(): pass\n",
                symbols=" zebra_secret ",
            )
        )
        db.commit()
    replay(GOOD)
    body = _ask(c, rid, "Where is zebra_secret defined?").json()
    assert body["status"] == "no_matches" and body["sources"] == []


def test_other_users_repository_is_not_found(sample_zip):
    _, rid = _user_with_repo(sample_zip)
    stranger = signed_up(f"qa{next(_counter)}@example.com", PW)
    assert _ask(stranger, rid).status_code == 404


def test_repository_that_is_not_indexed_is_refused(sample_zip):
    c, rid = _user_with_repo(sample_zip)
    with SessionLocal() as db:
        db.get(Repository, rid).index_status = "indexing"
        db.commit()
    assert _ask(c, rid).status_code == 409


def test_question_length_is_validated(sample_zip):
    c, rid = _user_with_repo(sample_zip)
    assert _ask(c, rid, "hi").status_code == 422
    assert _ask(c, rid, "x" * 501).status_code == 422


def test_questions_that_reach_the_model_use_the_review_quota(sample_zip, settings, monkeypatch, replay):
    monkeypatch.setattr(settings, "reviews_per_hour", 1)
    c, rid = _user_with_repo(sample_zip)
    replay(GOOD)
    assert _ask(c, rid, "How are kubernetes manifests deployed?").json()["status"] == "no_matches"  # free
    assert _ask(c, rid).json()["status"] == "answered"
    assert _ask(c, rid).status_code == 429


def test_question_text_is_not_stored(sample_zip, replay):
    c, rid = _user_with_repo(sample_zip)
    replay(GOOD)
    _ask(c, rid, "Where is the discount applied for customer Alice?")
    with SessionLocal() as db:
        events = db.query(AuditEvent).filter_by(action="repository.ask").all()
    assert events and all("Alice" not in str(e.detail) for e in events)
