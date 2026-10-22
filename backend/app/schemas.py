"""Request/response models for the HTTP API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)


class UserOut(ORM):
    id: int
    email: str


class RepositoryOut(ORM):
    id: int
    name: str
    source_type: str
    source_ref: str
    ai_review_allowed: bool
    index_status: str
    index_error: str | None
    indexed_at: datetime | None
    file_count: int
    total_bytes: int
    skipped: dict
    created_at: datetime


class LocalRepoIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[\w.\- ]+$")
    path: str = Field(min_length=1, max_length=1024)


class GitHubRepoIn(BaseModel):
    full_name: str = Field(max_length=140)


class RepositoryPatch(BaseModel):
    ai_review_allowed: bool | None = None


class ReviewIn(BaseModel):
    kind: Literal["full", "diff", "pull_request"]
    base_ref: str | None = Field(default=None, max_length=200)
    head_ref: str | None = Field(default=None, max_length=200)
    pr_number: int | None = Field(default=None, ge=1)
    use_ai: bool = False


class ReviewOut(ORM):
    id: int
    repository_id: int
    kind: str
    base_ref: str | None
    head_ref: str | None
    pull_request_id: int | None
    use_ai: bool
    status: str
    stage: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    stats: dict
    severity_counts: dict[str, int] = {}
    pr_number: int | None = None
    pr_title: str | None = None


class FindingOut(ORM):
    id: int
    review_id: int
    source: str
    analyzer: str
    analyzer_version: str
    rule_id: str | None
    title: str
    description: str
    severity: str
    category: str
    path: str
    start_line: int
    end_line: int
    evidence: str
    reasoning: str | None
    suggested_fix: str | None
    suggested_test: str | None
    confidence: str | None
    limitations: str | None
    doc_url: str | None
    my_feedback: str | None = None


class ChangedFileOut(ORM):
    path: str
    status: str
    additions: int
    deletions: int
    patch: str | None


class TestSuggestionOut(ORM):
    id: int
    source: str
    target: str
    path: str
    start_line: int
    rationale: str
    test_code: str


class FeedbackIn(BaseModel):
    verdict: Literal["useful", "incorrect", "duplicate", "not_actionable"]
    comment: str | None = Field(default=None, max_length=2000)


class FileContent(BaseModel):
    path: str
    language: str
    content: str
    line_count: int
