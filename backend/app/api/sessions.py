"""
Session APIs + Workflow Execution APIs.

- POST   /sessions             create a session
- GET    /sessions             list session history
- GET    /sessions/{id}        session detail (incl. report if complete)
- GET    /sessions/{id}/run    SSE stream: executes the LangGraph workflow,
                                emitting one event per node, then persists
                                the final report
"""

import json
import logging
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core import db
from app.graph.workflow import research_graph
from app.models.schemas import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionDetailResponse,
    SessionSummary,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionCreateResponse)
def create_session(payload: SessionCreateRequest):
    session_id = str(uuid.uuid4())
    db.create_session(
        session_id=session_id,
        company_name=payload.company_name,
        website=payload.website or "",
        objective=payload.objective,
    )
    return SessionCreateResponse(session_id=session_id, status="pending")


@router.get("", response_model=list[SessionSummary])
def list_sessions():
    return db.list_sessions()


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session(session_id: str):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    report = db.get_report(session_id)
    return SessionDetailResponse(**session, report=report)


@router.get("/{session_id}/run")
def run_session(session_id: str):
    """
    Streams workflow progress as Server-Sent Events.

    Each event is a JSON-encoded ProgressEvent. The frontend should
    open this with EventSource and update the progress UI per node;
    the final event (done=true) includes the full report.
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    def event_stream():
        initial_state = {
            "session_id": session_id,
            "company_name": session["company_name"],
            "website": session["website"],
            "objective": session["objective"],
        }
        config = {"configurable": {"thread_id": session_id}}
        graph_state = research_graph.get_state(config)

        if session["status"] == "running" and graph_state.next:
            stream_input = None
            logger.info("Resuming session %s from checkpoint", session_id)
        else:
            if session["status"] in ("pending", "failed"):
                research_graph.checkpointer.delete_thread(session_id)
            stream_input = initial_state

        db.update_session_status(session_id, status="running")

        try:
            final_report = None
            research_mode = None

            for step in research_graph.stream(stream_input, config=config):
                for node_name, update in step.items():
                    status_msg = update.get("status", "")
                    research_mode = update.get("research_mode", research_mode)

                    event = {
                        "node": node_name,
                        "status": status_msg,
                        "done": False,
                    }
                    yield _sse(event)

                    if "final_report" in update:
                        final_report = update["final_report"]

            if final_report is None:
                raise RuntimeError("Workflow finished without producing a report")

            report_dict = (
                final_report.model_dump()
                if hasattr(final_report, "model_dump")
                else final_report
            )

            db.save_report(session_id, report_dict)
            db.update_session_status(
                session_id, status="completed", research_mode=research_mode
            )

            yield _sse(
                {
                    "node": "report_generation",
                    "status": "Done",
                    "done": True,
                    "report": report_dict,
                }
            )

        except Exception as exc:  # noqa: BLE001
            logger.exception("Workflow run failed for session %s", session_id)
            db.update_session_status(session_id, status="failed", error=str(exc))
            yield _sse(
                {
                    "node": "error",
                    "status": "Workflow failed",
                    "done": True,
                    "error": str(exc),
                }
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"