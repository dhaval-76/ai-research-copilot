"""
Follow-up chat.

Deliberately NOT a LangGraph workflow -- per the locked design, the
mandatory LangGraph requirement is satisfied by the research workflow
(workflow.py). Chat is a plain LangChain call: the full report + recent
conversation history fit comfortably in context for a single company,
so no retrieval/vector store is needed at this scale.

(Documented upgrade path in engineering-decisions.md: if chat needed to
span multiple sessions/companies, a small router+retrieval graph would
be the next step.)
"""

import logging
from app.core.config import get_chat_model

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 10


def answer_followup(report: dict, history: list[dict], question: str) -> str:
    """
    Answer a follow-up question grounded in the research report.

    `report` is the StructuredReport as a dict.
    `history` is prior chat messages: [{"role": "user"|"assistant", "content": ...}]
    """
    llm = get_chat_model()

    report_text = _format_report(report)
    history_text = "\n".join(
        f"{m['role'].capitalize()}: {m['content']}"
        for m in history[-MAX_HISTORY_MESSAGES:]
    )

    prompt = (
        "You are a research copilot. Answer the user's follow-up question "
        "using ONLY the research report below. If the report doesn't "
        "contain the answer, say so plainly and suggest what additional "
        "research would be needed -- do not fabricate details.\n\n"
        f"--- REPORT ---\n{report_text}\n--- END REPORT ---\n\n"
        f"--- CONVERSATION SO FAR ---\n{history_text}\n--- END CONVERSATION ---\n\n"
        f"User question: {question}"
    )

    try:
        response = llm.invoke(prompt)
        return response.content
    except Exception as exc:  # noqa: BLE001
        logger.error("answer_followup failed: %s", exc)
        return (
            "Sorry, I couldn't generate a response just now due to an "
            "internal error. Please try again."
        )


def _format_report(report: dict) -> str:
    sections = [
        "company_overview",
        "products_and_services",
        "target_customers",
        "business_signals",
        "risks_and_challenges",
    ]
    parts = []
    for key in sections:
        section = report.get(key, {})
        parts.append(f"## {key}\n{section.get('content', '')}")

    parts.append(
        "## suggested_discovery_questions\n"
        + "\n".join(f"- {q}" for q in report.get("suggested_discovery_questions", []))
    )
    parts.append(
        "## suggested_outreach_strategy\n"
        + report.get("suggested_outreach_strategy", {}).get("content", "")
    )
    parts.append("## unknowns\n" + "\n".join(f"- {u}" for u in report.get("unknowns", [])))
    parts.append("## sources\n" + "\n".join(report.get("sources", [])))

    return "\n\n".join(parts)