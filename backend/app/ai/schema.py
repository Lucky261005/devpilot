"""Structured output schema the model must return. Validated with Pydantic on every response."""

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low", "info"]
Category = Literal[
    "bug",
    "security",
    "error_handling",
    "resource",
    "logic",
    "performance",
    "maintainability",
    "testing",
]


class AIFinding(BaseModel):
    title: str = Field(max_length=200, description="One-line summary of the problem.")
    description: str = Field(max_length=2000, description="What is wrong and why it matters.")
    severity: Severity
    category: Category
    path: str = Field(description="File path exactly as shown in a FILE header.")
    start_line: int = Field(ge=1, description="First line, using the numbers shown.")
    end_line: int = Field(ge=1, description="Last line, using the numbers shown.")
    evidence: str = Field(max_length=2000, description="Code copied verbatim from the cited lines, without numbers.")
    reasoning: str = Field(max_length=2000, description="Short justification for a developer.")
    suggested_fix: str = Field(max_length=3000)
    suggested_test: str = Field(max_length=3000, description="A regression test that would fail now.")
    confidence: Literal["low", "medium", "high"]


class AITestSuggestion(BaseModel):
    target: str = Field(max_length=300, description="Function or behavior under test.")
    path: str
    start_line: int = Field(ge=1)
    rationale: str = Field(max_length=1500)
    test_code: str = Field(max_length=5000)


class AIReview(BaseModel):
    summary: str = Field(max_length=2000, description="Two or three sentences about the change.")
    findings: list[AIFinding] = Field(max_length=20)
    unconfirmed: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Suspicions the code shown does not prove, one sentence each. Not findings.",
    )
    test_suggestions: list[AITestSuggestion] = Field(max_length=5)
