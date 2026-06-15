"""
Request/response schemas for the API layer.

Kept separate from app.graph.state -- the graph's internal state shape
(GraphState) is an implementation detail; these schemas are the public
API contract and can evolve independently.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field

from app.graph.state import StructuredReport


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class SessionCreateRequest(BaseModel):
    company_name: str = Field(..., min_length=1, examples=["Stripe"])
    website: str = Field(..., min_length=1, examples=["https://stripe.com"])
    objective: str = Field(
        ...,
        min_length=1,
        examples=[
            "Preparing for a sales call to pitch our fraud detection API"
        ],
    )


class SessionCreateResponse(BaseModel):
    session_id: str
    status: str
    existing: bool = False


class SessionSummary(BaseModel):
    id: str
    company_name: str
    website: str
    objective: str
    research_mode: Optional[str] = None
    status: str
    error: Optional[str] = None
    created_at: str
    updated_at: str


class ProgressEvent(BaseModel):
    """
    One SSE event emitted while a workflow run is in progress.

    `node` is the LangGraph node that just completed; `status` is the
    human-readable message that node set in GraphState; `done` is true
    only on the final event, which also carries the report.
    """

    node: str
    status: str
    done: bool = False
    report: Optional[StructuredReport] = None
    error: Optional[str] = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: Optional[str] = None


class SessionDetailResponse(SessionSummary):
    report: Optional[StructuredReport] = None
    progress_events: list[ProgressEvent] = []
    chat_messages: list[ChatMessage] = []


# ---------------------------------------------------------------------------
# Workflow progress (streamed)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    message: ChatMessage


class ChatHistoryResponse(BaseModel):
    messages: list[ChatMessage]