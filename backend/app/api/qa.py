from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_repo
from app.api.reviews import _admit_user_review
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.models import AuditEvent, User
from app.services.qa import answer_question

router = APIRouter(prefix="/api/repositories", tags=["repositories"])


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@router.post("/{repo_id}/ask")
def ask_repository(
    repo_id: int,
    body: AskIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
):
    """Answer a question from this repository's indexed code (services/qa.py). Ownership is checked
    first and retrieval is scoped to this repository's id. A question that reaches the model counts
    toward the user's hourly review quota. The question text is not logged or stored."""
    repo = owned_repo(repo_id, db, user)
    if repo.index_status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "Repository is not indexed.")
    result = answer_question(
        db,
        repo.id,
        body.question.strip(),
        settings,
        ai_allowed=repo.ai_review_allowed,
        before_llm=lambda: _admit_user_review(db, user, settings.reviews_per_hour),
    )
    db.add(
        AuditEvent(
            user_id=user.id, action="repository.ask", detail={"repository_id": repo.id, "status": result["status"]}
        )
    )
    db.commit()
    return result
