"""
Shared state definition for the AI Research Copilot LangGraph workflow.

This module defines:
- ResearchTask: a single unit of research work created by the Planner
- ReportSection: a structured, confidence-scored piece of the final report
- StructuredReport: the full report shape returned to the frontend
- GraphState: the TypedDict that flows through every node in the graph
"""

from typing import Literal, Optional, TypedDict
from pydantic import BaseModel, Field


ResearchMode = Literal["sales", "investment", "competitive", "general"]
Confidence = Literal["high", "medium", "low"]


class ResearchTask(BaseModel):
    """A single research sub-task produced by the Planner node."""

    topic: str = Field(..., description="Short label, e.g. 'target_customers'")
    query: str = Field(..., description="Search query to execute for this topic")
    rationale: str = Field(
        default="", description="Why this topic matters for the objective"
    )


class RawFinding(BaseModel):
    """Raw search results collected for a single research task."""

    topic: str
    query: str
    snippets: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"
    error: Optional[str] = None


class ReportSection(BaseModel):
    """A single analyzed section of the final report."""

    content: str
    confidence: Confidence = "medium"
    sources: list[str] = Field(default_factory=list)


class StructuredReport(BaseModel):
    """Full structured report returned to the user."""

    company_overview: ReportSection
    products_and_services: ReportSection
    target_customers: ReportSection
    business_signals: ReportSection
    risks_and_challenges: ReportSection
    suggested_discovery_questions: list[str] = Field(default_factory=list)
    suggested_outreach_strategy: ReportSection
    unknowns: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class GraphState(TypedDict, total=False):
    """
    The object passed between every node in the LangGraph workflow.

    `total=False` so each node can return a partial update; LangGraph
    merges these into the running state.
    """

    # --- session inputs ---
    session_id: str
    company_name: str
    website: str
    objective: str

    # --- planner outputs ---
    research_mode: ResearchMode
    research_plan: list[ResearchTask]
    needs_competitor_research: bool

    # --- research outputs ---
    raw_research: dict[str, RawFinding]  # keyed by topic

    # --- analysis outputs ---
    analysis: dict[str, ReportSection]  # keyed by report section name

    # --- quality check ---
    quality_issues: list[str]  # topic names that need re-research
    retry_count: int
    max_retries: int

    # --- final output ---
    final_report: StructuredReport

    # --- bookkeeping / observability ---
    status: str  # human-readable current step, surfaced to frontend
    error_log: list[str]
