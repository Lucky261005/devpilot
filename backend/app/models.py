"""ORM models. See docs/database.md for the ER diagram and retention rules."""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))


class UserSession(TimestampMixin, Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GitHubAccount(TimestampMixin, Base):
    __tablename__ = "github_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    github_login: Mapped[str] = mapped_column(String(255))
    encrypted_token: Mapped[str] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(String(255), default="")


class Repository(TimestampMixin, Base):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("owner_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(16))  # archive | local | github
    # local: absolute path; github: "owner/repo"; archive: original filename
    source_ref: Mapped[str] = mapped_column(String(1024))
    # Explicit opt-in before any source from this repository is sent to an external LLM.
    ai_review_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    index_status: Mapped[str] = mapped_column(String(16), default="pending")
    index_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    total_bytes: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[dict] = mapped_column(JSON, default=dict)  # reason -> count
    snapshot_dir: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    reviews: Mapped[list["ReviewJob"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan", passive_deletes=True
    )


class CodeChunk(Base):
    __tablename__ = "code_chunks"
    __table_args__ = (Index("ix_chunks_repo_path", "repository_id", "path"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(1024))
    language: Mapped[str] = mapped_column(String(32))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    # Space-separated identifiers found in the chunk, for identifier search.
    symbols: Mapped[str] = mapped_column(Text, default="")


class PullRequest(TimestampMixin, Base):
    __tablename__ = "pull_requests"
    __table_args__ = (UniqueConstraint("repository_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(1024))
    author: Mapped[str] = mapped_column(String(255))
    base_sha: Mapped[str] = mapped_column(String(64))
    head_sha: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(String(1024))


class ReviewJob(TimestampMixin, Base):
    __tablename__ = "review_jobs"
    __table_args__ = (Index("ix_jobs_status_created", "status", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    pull_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="SET NULL"), nullable=True
    )
    # full = whole snapshot; diff = local git base..head; pull_request = GitHub PR
    kind: Mapped[str] = mapped_column(String(16))
    base_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    head_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    use_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|completed|failed
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # timings, analyzer versions, model, token usage, dropped-finding counts
    stats: Mapped[dict] = mapped_column(JSON, default=dict)

    repository: Mapped[Repository] = relationship(back_populates="reviews")
    changed_files: Mapped[list["ChangedFile"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    findings: Mapped[list["Finding"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    test_suggestions: Mapped[list["TestSuggestion"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class ChangedFile(Base):
    __tablename__ = "changed_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("review_jobs.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(16))  # added|modified|deleted|renamed
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    patch: Mapped[str | None] = mapped_column(Text, nullable=True)


class Finding(TimestampMixin, Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("review_jobs.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16))  # static | ai
    analyzer: Mapped[str] = mapped_column(String(64))  # ruff, bandit, llm:<model>
    analyzer_version: Mapped[str] = mapped_column(String(64))
    rule_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))  # critical|high|medium|low|info
    category: Mapped[str] = mapped_column(String(32))
    path: Mapped[str] = mapped_column(String(1024))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    evidence: Mapped[str] = mapped_column(Text)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_test: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)  # low|medium|high
    limitations: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    feedback: Mapped[list["FindingFeedback"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class FindingFeedback(TimestampMixin, Base):
    __tablename__ = "finding_feedback"
    __table_args__ = (UniqueConstraint("finding_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    review_id: Mapped[int] = mapped_column(ForeignKey("review_jobs.id", ondelete="CASCADE"))
    verdict: Mapped[str] = mapped_column(String(32))  # useful|incorrect|duplicate|not_actionable
    analyzer: Mapped[str] = mapped_column(String(64))
    analyzer_version: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class TestSuggestion(TimestampMixin, Base):
    __tablename__ = "test_suggestions"
    __test__ = False  # keep pytest from collecting this class
    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("review_jobs.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16))  # static | ai
    target: Mapped[str] = mapped_column(String(512))  # e.g. "pkg/mod.py::func"
    path: Mapped[str] = mapped_column(String(1024))
    start_line: Mapped[int] = mapped_column(Integer)
    rationale: Mapped[str] = mapped_column(Text)
    test_code: Mapped[str] = mapped_column(Text)
    finding_id: Mapped[int | None] = mapped_column(ForeignKey("findings.id", ondelete="SET NULL"), nullable=True)


class AuditEvent(TimestampMixin, Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
