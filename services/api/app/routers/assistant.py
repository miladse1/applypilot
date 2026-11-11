from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import AssistantConversation, User
from app.routers.common import not_found
from app.services.assistant import chat, conversation_messages

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    context: dict | None = None


@router.post("/chat")
def send(payload: ChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return chat(db, user, payload.message, conversation_id=payload.conversation_id, context=payload.context)


@router.get("/conversations")
def conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(AssistantConversation).where(AssistantConversation.user_id == user.id).order_by(AssistantConversation.updated_at.desc())
    ).all()
    return [{"id": row.id, "title": row.title, "updated_at": row.updated_at.isoformat() if row.updated_at else None} for row in rows[:50]]


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(AssistantConversation, conversation_id)
    if row is None or row.user_id != user.id:
        raise not_found()
    return {"id": row.id, "title": row.title, "messages": conversation_messages(db, row)}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(AssistantConversation, conversation_id)
    if row is None or row.user_id != user.id:
        raise not_found()
    db.delete(row)
    db.commit()
    return {"ok": True}
