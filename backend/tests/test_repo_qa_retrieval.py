"""Q&A retrieval relevance on a small, fixed repository: which file comes first for realistic questions."""

import pytest

import app.services.qa as qa
from app.core.db import SessionLocal
from app.models import CodeChunk, Repository, User
from tests.conftest import _counter, signed_up

FILES = {
    "app/security/session.py": (
        "def verify_token(token):\n    # check the login session cookie\n    return lookup(token)\n",
        " verify_token ",
    ),
    "app/settings.py": (
        "class Settings:\n    database_url: str\n\ndef validate_env(values):\n    require(values, 'SECRET_KEY')\n",
        " Settings validate_env ",
    ),
    "app/orders/load.py": (
        "def load_order_items(order_id):\n    return db.fetch(order_id)\n",
        " load_order_items ",
    ),
    "app/payments/refund.py": (
        "def issue_refund(amount):\n    ledger.add(-amount)\n",
        " issue_refund ",
    ),
    "app/payments/charge.py": (
        "def charge_card(amount):\n    gateway.charge(amount)\n",
        " charge_card ",
    ),
    "README.md": ("Orders, payments and settings for the shop. Run make test.\n", ""),
}


@pytest.fixture
def repo_id():
    email = f"ret{next(_counter)}@example.com"
    signed_up(email, "correct-horse-9")
    with SessionLocal() as db:
        owner = db.query(User).filter_by(email=email).one()
        repo = Repository(
            owner_id=owner.id, name="shop", source_type="archive", source_ref="shop.zip", index_status="ready"
        )
        db.add(repo)
        db.flush()
        for path, (content, symbols) in FILES.items():
            lines = content.count("\n")
            db.add(
                CodeChunk(
                    repository_id=repo.id,
                    path=path,
                    language="python",
                    start_line=1,
                    end_line=lines,
                    content=content,
                    symbols=symbols,
                )
            )
        db.commit()
        return repo.id


def _top(repo_id: int, question: str) -> str | None:
    with SessionLocal() as db:
        found = qa.retrieve(db, repo_id, question)
    return found[0].path if found else None


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        # terminology mismatches
        ("Where is authentication handled?", "app/security/session.py"),
        ("Which file validates the environment configuration?", "app/settings.py"),
        ("Where are refunds issued?", "app/payments/refund.py"),
        # identifiers in the question
        ("What does loadOrderItems do?", "app/orders/load.py"),
        ("What does load_order_items return?", "app/orders/load.py"),
        ("How do we load order items?", "app/orders/load.py"),
        # file paths
        ("What is in the refund module?", "app/payments/refund.py"),
        ("Explain app/payments/charge.py", "app/payments/charge.py"),
    ],
)
def test_most_relevant_file_comes_first(repo_id, question, expected):
    assert _top(repo_id, question) == expected


def test_unrelated_question_finds_nothing(repo_id):
    assert _top(repo_id, "How are kubernetes pods scheduled?") is None


def test_stemming_keeps_at_least_four_letters():
    assert [qa.stem(w) for w in ("refunds", "validates", "configuration", "issued", "items", "pods", "uses")] == [
        "refund",
        "validat",
        "configur",
        "issu",
        "item",
        "pods",
        "uses",
    ]


def test_question_words_outweigh_synonyms():
    terms = dict(qa.search_terms("Where is authentication handled?"))
    assert terms["authentication"] == 2 and terms["authentic"] == 2
    assert terms["login"] == 1 and terms["session"] == 1
    assert len(qa.search_terms("auth config database error delete user endpoint test " * 3)) <= qa.MAX_TERMS
