"""
Chat APIs.

- POST /sessions/{id}/chat   ask a follow-up question (answered from report)
- GET  /sessions/{id}/chat   get chat history for the session
"""

from fastapi import APIRouter, HTTPException

from app.core import db
from app.graph.chat import answer_followup
from app.models.schemas import ChatHistoryResponse, ChatMessage, ChatRequest, ChatResponse

router = APIRouter(prefix="/sessions", tags=["chat"])


@router.post("/{session_id}/chat", response_model=ChatResponse)
def post_chat_message(session_id: str, payload: ChatRequest):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    report = db.get_report(session_id)
    if not report:
        raise HTTPException(
            status_code=409,
            detail="Report not ready yet -- run the workflow first",
        )

    history = db.get_chat_history(session_id)

    db.add_chat_message(session_id, role="user", content=payload.message)

    answer = answer_followup(report=report, history=history, question=payload.message)

    db.add_chat_message(session_id, role="assistant", content=answer)

    return ChatResponse(message=ChatMessage(role="assistant", content=answer))


@router.get("/{session_id}/chat", response_model=ChatHistoryResponse)
def get_chat_history(session_id: str):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    history = db.get_chat_history(session_id)
    return ChatHistoryResponse(
        messages=[ChatMessage(**m) for m in history]
    )