"""
Quick end-to-end test of the research graph -- run this BEFORE building
the API/frontend to catch LangGraph/LangChain version issues early.

Usage:
    cd backend
    pip install -r requirements.txt
    cp .env.example .env   # fill in GROQ_API_KEY
    python -m scripts.test_graph

Prints status updates as the graph streams through nodes, then dumps
the final report as JSON.
"""

import json
import logging

from app.graph.workflow import research_graph

logging.basicConfig(level=logging.INFO)


def main():
    initial_state = {
        "session_id": "test-session-1",
        "company_name": "Stripe",
        "website": "https://stripe.com",
        "objective": "Preparing for a sales call to pitch our fraud "
        "detection API as an add-on to their payments stack",
    }

    config = {"configurable": {"thread_id": initial_state["session_id"]}}

    print("=== Streaming workflow progress ===")
    for step in research_graph.stream(initial_state, config=config):
        for node_name, update in step.items():
            status = update.get("status", "")
            print(f"[{node_name}] {status}")

    print("\n=== Final state ===")
    final_state = research_graph.get_state(config).values
    report = final_state.get("final_report")

    if report is None:
        print("No final_report in state -- check error_log:")
        print(final_state.get("error_log"))
        return

    # report may be a pydantic model or dict depending on checkpointer
    # serialization -- handle both
    if hasattr(report, "model_dump"):
        report = report.model_dump()

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
