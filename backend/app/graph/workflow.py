"""
Graph assembly for the AI Research Copilot.

Wires together the nodes from nodes.py into a StateGraph with three
conditional edges:

  1. planner -> [competitor_research | research]   (objective-driven)
  2. research -> [gap_fill | analysis]              (data-richness check)
  3. quality_check -> [gap_fill | report_generation] (bounded retry loop)

Persistence/recoverability within a single process run is provided by
LangGraph's built-in MemorySaver checkpointer: every node transition is
checkpointed in-memory, so a session can be resumed/re-streamed by
thread_id while the process is alive (e.g. frontend reconnects mid-run).

Cross-restart persistence (the spec's "Persistence Layer" requirement)
is handled separately at the API layer via SQLite -- session metadata
and the final report are written there once the graph completes.
Swapping MemorySaver for a SqliteSaver/PostgresSaver checkpointer later
would extend recoverability to process crashes too; see
engineering-decisions.md for this tradeoff.
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.graph.state import GraphState
from app.graph import nodes


def build_graph():
    graph = StateGraph(GraphState)

    graph.add_node("planner", nodes.planner_node)
    graph.add_node("competitor_research", nodes.competitor_research_node)
    graph.add_node("research", nodes.research_node)
    graph.add_node("gap_fill", nodes.gap_fill_node)
    graph.add_node("analysis", nodes.analysis_node)
    graph.add_node("quality_check", nodes.quality_check_node)
    graph.add_node("report_generation", nodes.report_generation_node)

    graph.set_entry_point("planner")

    # Conditional edge #1: objective-driven competitor research path
    graph.add_conditional_edges(
        "planner",
        nodes.route_after_planner,
        {"competitor_research": "competitor_research", "research": "research"},
    )
    graph.add_edge("competitor_research", "research")

    # Conditional edge #2: data-richness check
    graph.add_conditional_edges(
        "research",
        nodes.route_after_research,
        {"gap_fill": "gap_fill", "analysis": "analysis"},
    )
    # gap_fill always loops back into research with a broadened plan
    graph.add_edge("gap_fill", "research")

    graph.add_edge("analysis", "quality_check")

    # Conditional edge #3: bounded quality retry loop
    graph.add_conditional_edges(
        "quality_check",
        nodes.route_after_quality_check,
        {"gap_fill": "gap_fill", "report_generation": "report_generation"},
    )

    graph.add_edge("report_generation", END)

    checkpointer = MemorySaver()

    return graph.compile(checkpointer=checkpointer)


# Compiled once at import time; reused across requests
research_graph = build_graph()
