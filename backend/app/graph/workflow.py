"""
Graph assembly for the AI Research Copilot.

Wires together the nodes from nodes.py into a StateGraph with three
conditional edges:

  1. planner -> [competitor_research | research]   (objective-driven)
  2. research -> [gap_fill | analysis]              (data-richness check)
  3. quality_check -> [gap_fill | report_generation] (bounded retry loop)

Persistence/recoverability is provided by LangGraph's SqliteSaver
checkpointer: every node transition is written to a SQLite file keyed by
session_id (thread_id), so a session can be resumed after a client
reconnect or a server restart. Session metadata and the final report are
stored separately in app.db once the graph completes.
"""

from langgraph.graph import StateGraph, END

from app.core.checkpoint import get_checkpointer
from app.graph.state import GraphState
from app.graph import nodes


def build_graph():
    graph = StateGraph(GraphState)

    graph.add_node("planner", nodes.planner_node)
    graph.add_node("competitor_research", nodes.competitor_research_node)
    graph.add_node("research", nodes.research_node)
    graph.add_node("gap_fill", nodes.gap_fill_node)
    graph.add_node("analyze", nodes.analysis_node)
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
        {"gap_fill": "gap_fill", "analysis": "analyze"},
    )
    # gap_fill always loops back into research with a broadened plan
    graph.add_edge("gap_fill", "research")

    graph.add_edge("analyze", "quality_check")

    # Conditional edge #3: bounded quality retry loop
    graph.add_conditional_edges(
        "quality_check",
        nodes.route_after_quality_check,
        {"gap_fill": "gap_fill", "report_generation": "report_generation"},
    )

    graph.add_edge("report_generation", END)

    return graph.compile(checkpointer=get_checkpointer())


# Compiled once at import time; reused across requests
research_graph = build_graph()
