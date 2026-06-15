"""
LangGraph node implementations for the AI Research Copilot.

Each node is a plain function: (GraphState) -> partial GraphState update.
LangGraph merges the returned dict into the running state.

Nodes:
- planner_node            : classifies objective, builds research plan
- competitor_research_node: adds a competitor-focused task (conditional path)
- research_node           : executes web searches for pending tasks
- analysis_node           : synthesizes raw research into report sections
- quality_check_node      : flags weak sections for targeted re-research
- report_generation_node  : compiles the final structured report

Routing functions (used by add_conditional_edges):
- route_after_planner
- route_after_research
- route_after_quality_check
"""

import logging
from pydantic import BaseModel, Field

from app.core.config import get_settings, get_chat_model
from app.core.search import web_search
from app.graph.state import (
    GraphState,
    ResearchTask,
    RawFinding,
    ReportSection,
    StructuredReport,
    ResearchMode,
    Confidence,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured-output schemas (LLM-facing, not part of GraphState directly)
# ---------------------------------------------------------------------------


class PlannerOutput(BaseModel):
    research_mode: ResearchMode
    needs_competitor_research: bool = Field(
        description="True if objective implies investment, competitive, "
        "or partnership analysis where competitor context matters"
    )
    research_plan: list[ResearchTask]


class AnalysisOutput(BaseModel):
    company_overview: ReportSection
    products_and_services: ReportSection
    target_customers: ReportSection
    business_signals: ReportSection
    risks_and_challenges: ReportSection


class QualityCheckOutput(BaseModel):
    weak_topics: list[str] = Field(
        default_factory=list,
        description="Topic names from research_plan whose findings are "
        "too thin or vague to support a confident report section",
    )
    reasoning: str = ""


class ReportExtras(BaseModel):
    suggested_discovery_questions: list[str]
    suggested_outreach_strategy: ReportSection
    unknowns: list[str]


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


def planner_node(state: GraphState) -> dict:
    """
    Reads company/website/objective and produces:
    - research_mode: drives conditional routing downstream
    - needs_competitor_research: conditional edge #1
    - research_plan: list of (topic, query) tasks for the research node
    """
    llm = get_chat_model().with_structured_output(PlannerOutput)

    prompt = (
        "You are a research planner for a B2B sales/research copilot.\n"
        f"Company: {state['company_name']}\n"
        f"Website: {state.get('website', 'unknown')}\n"
        f"Research objective: {state['objective']}\n\n"
        "Classify the objective into one research_mode: "
        "'sales' (preparing for a sales/discovery call), "
        "'investment' (due diligence / funding), "
        "'competitive' (competitor/market analysis), or 'general'.\n"
        "Set needs_competitor_research=true only if the mode is "
        "'investment' or 'competitive', or the objective explicitly "
        "asks about competitors/market position.\n\n"
        "Produce a research_plan covering these topics (use these exact "
        "topic names): company_overview, products_and_services, "
        "target_customers, business_signals, risks_and_challenges. "
        "For each, write a concrete web search query that includes the "
        "company name."
    )

    try:
        result: PlannerOutput = llm.invoke(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.error("planner_node failed: %s", exc)
        # Fallback plan keeps the workflow moving even if the LLM call fails
        result = PlannerOutput(
            research_mode="general",
            needs_competitor_research=False,
            research_plan=[
                ResearchTask(
                    topic=t,
                    query=f"{state['company_name']} {t.replace('_', ' ')}",
                )
                for t in (
                    "company_overview",
                    "products_and_services",
                    "target_customers",
                    "business_signals",
                    "risks_and_challenges",
                )
            ],
        )

    return {
        "research_mode": result.research_mode,
        "needs_competitor_research": result.needs_competitor_research,
        "research_plan": result.research_plan,
        "raw_research": {},
        "retry_count": 0,
        "max_retries": get_settings().max_research_retries,
        "error_log": [],
        "status": "Planning complete — research mode: "
        f"{result.research_mode}",
    }


def route_after_planner(state: GraphState) -> str:
    """Conditional edge #1: objective-driven competitor research path."""
    return "competitor_research" if state.get("needs_competitor_research") else "research"


# ---------------------------------------------------------------------------
# Competitor research (conditional extra node)
# ---------------------------------------------------------------------------


def competitor_research_node(state: GraphState) -> dict:
    """
    Adds a competitor-landscape task to the research plan.
    Reached only when the planner decided objective_mode requires it
    (investment / competitive analysis).
    """
    plan = list(state.get("research_plan", []))
    plan.append(
        ResearchTask(
            topic="competitive_landscape",
            query=f"{state['company_name']} competitors alternatives market position",
            rationale="Investment/competitive objective requires competitor context",
        )
    )
    return {
        "research_plan": plan,
        "status": "Added competitor-landscape research (objective requires it)",
    }


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------


def research_node(state: GraphState) -> dict:
    """
    Executes web search for every task in research_plan that doesn't yet
    have a result in raw_research. This makes the node naturally reusable
    for the initial pass AND the gap-fill retry loop (quality_issues
    removes weak topics from raw_research before looping back here).
    """
    raw_research = dict(state.get("raw_research", {}))
    plan: list[ResearchTask] = state.get("research_plan", [])

    for task in plan:
        if task.topic in raw_research:
            continue  # already researched (and not flagged as weak)

        results = web_search(task.query)
        snippets = [r["snippet"] for r in results if r.get("snippet")]
        urls = [r["url"] for r in results if r.get("url")]

        confidence: Confidence
        if len(snippets) >= 3:
            confidence = "high"
        elif len(snippets) >= 1:
            confidence = "medium"
        else:
            confidence = "low"

        raw_research[task.topic] = RawFinding(
            topic=task.topic,
            query=task.query,
            snippets=snippets,
            source_urls=urls,
            confidence=confidence,
            error=None if results else "no search results",
        )

    low_conf = [t for t, f in raw_research.items() if f.confidence == "low"]
    status = (
        f"Research complete for {len(raw_research)} topics "
        f"({len(low_conf)} low-confidence)"
    )

    return {"raw_research": raw_research, "status": status}


def route_after_research(state: GraphState) -> str:
    """
    Conditional edge #2 (data-richness check): if more than half of the
    researched topics came back low-confidence and we still have a retry
    budget, do one broadened gap-fill pass before analysis. Otherwise
    proceed to analysis -- low-confidence topics simply feed the
    'Unknowns' section later.
    """
    raw_research = state.get("raw_research", {})
    if not raw_research:
        return "analysis"

    low_conf_topics = [
        t for t, f in raw_research.items() if f.confidence == "low"
    ]
    is_majority_weak = len(low_conf_topics) > len(raw_research) / 2
    retries_left = state.get("retry_count", 0) < state.get("max_retries", 1)

    if is_majority_weak and retries_left:
        return "gap_fill"
    return "analysis"


def gap_fill_node(state: GraphState) -> dict:
    """
    Broadens queries for low-confidence topics and clears them from
    raw_research so research_node re-attempts them with a simpler query.
    Increments retry_count to bound the loop.
    """
    raw_research = dict(state.get("raw_research", {}))
    plan: list[ResearchTask] = list(state.get("research_plan", []))

    weak_topics = [t for t, f in raw_research.items() if f.confidence == "low"]

    new_plan = []
    for task in plan:
        if task.topic in weak_topics:
            # Broaden: drop extra qualifiers, just company name + topic
            broadened = ResearchTask(
                topic=task.topic,
                query=f"{state['company_name']} {task.topic.replace('_', ' ')}",
                rationale="broadened after low-confidence first pass",
            )
            new_plan.append(broadened)
            raw_research.pop(task.topic, None)
        else:
            new_plan.append(task)

    return {
        "research_plan": new_plan,
        "raw_research": raw_research,
        "retry_count": state.get("retry_count", 0) + 1,
        "status": f"Broadening queries for {len(weak_topics)} weak topic(s)",
    }


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def analysis_node(state: GraphState) -> dict:
    """
    Synthesizes raw_research into the five core analytical report sections.
    Uses structured output to enforce schema and pulls confidence/sources
    through from the underlying findings (grounding -- the LLM is not
    asked to invent confidence levels).
    """
    llm = get_chat_model().with_structured_output(AnalysisOutput)

    raw_research: dict[str, RawFinding] = state.get("raw_research", {})
    research_text = "\n\n".join(
        f"## {topic}\nQuery: {f.query}\n"
        + "\n".join(f"- {s}" for s in f.snippets)
        + (f"\n(no results found)" if not f.snippets else "")
        for topic, f in raw_research.items()
    )

    prompt = (
        f"Company: {state['company_name']}\n"
        f"Objective: {state['objective']}\n\n"
        "Below is raw web research, grouped by topic. Synthesize it into "
        "the five report sections. For each section, set confidence based "
        "on how well-supported the content is by the research below "
        "('low' if the underlying topic had no results -- do not "
        "fabricate details in that case, instead state what is unknown). "
        "List the source URLs you actually drew from in `sources` for "
        "each section.\n\n"
        f"--- RAW RESEARCH ---\n{research_text}\n--- END RAW RESEARCH ---"
    )

    try:
        result: AnalysisOutput = llm.invoke(prompt)
        analysis = result.model_dump()
    except Exception as exc:  # noqa: BLE001
        logger.error("analysis_node failed: %s", exc)
        analysis = {
            section: ReportSection(
                content="Analysis unavailable due to an internal error.",
                confidence="low",
            ).model_dump()
            for section in (
                "company_overview",
                "products_and_services",
                "target_customers",
                "business_signals",
                "risks_and_challenges",
            )
        }

    return {"analysis": analysis, "status": "Analysis complete"}


# ---------------------------------------------------------------------------
# Quality check
# ---------------------------------------------------------------------------


def quality_check_node(state: GraphState) -> dict:
    """
    Flags analysis sections that are low-confidence or whose underlying
    research topic was empty. Maps flagged sections back to research_plan
    topic names so the gap-fill loop can target them specifically.
    """
    analysis: dict = state.get("analysis", {})
    weak_topics = [
        topic
        for topic, section in analysis.items()
        if section.get("confidence") == "low"
    ]

    return {
        "quality_issues": weak_topics,
        "status": (
            f"Quality check: {len(weak_topics)} weak section(s)"
            if weak_topics
            else "Quality check passed"
        ),
    }


def route_after_quality_check(state: GraphState) -> str:
    """
    Conditional edge #3: targeted retry loop. Only loops back if there
    are flagged sections AND we haven't exhausted the retry budget --
    bounded so a persistently low-data company can't loop forever.
    """
    weak_topics = state.get("quality_issues", [])
    retries_left = state.get("retry_count", 0) < state.get("max_retries", 1)

    if weak_topics and retries_left:
        return "gap_fill"
    return "report_generation"


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def report_generation_node(state: GraphState) -> dict:
    """
    Compiles the final StructuredReport: takes the analyzed sections as-is,
    and asks the LLM only for the derived content (discovery questions,
    outreach strategy, unknowns). Aggregates all source URLs seen across
    research for the top-level `sources` field.
    """
    llm = get_chat_model().with_structured_output(ReportExtras)

    analysis: dict = state.get("analysis", {})
    raw_research: dict[str, RawFinding] = state.get("raw_research", {})

    all_sources = sorted(
        {url for f in raw_research.values() for url in f.source_urls}
    )
    unknown_topics = [
        topic for topic, f in raw_research.items() if f.confidence == "low"
    ]

    analysis_text = "\n\n".join(
        f"## {name}\n{section.get('content', '')}"
        for name, section in analysis.items()
    )

    prompt = (
        f"Company: {state['company_name']}\n"
        f"Objective: {state['objective']}\n"
        f"Research mode: {state.get('research_mode', 'general')}\n\n"
        "Based on this analysis, produce:\n"
        "1. suggested_discovery_questions: 4-6 sharp questions for a "
        "discovery call tailored to this objective.\n"
        "2. suggested_outreach_strategy: a short ReportSection with a "
        "concrete outreach angle for this objective.\n"
        "3. unknowns: list specific things that remain unclear "
        f"(include these under-researched topics if relevant: "
        f"{', '.join(unknown_topics) or 'none'}).\n\n"
        f"--- ANALYSIS ---\n{analysis_text}\n--- END ANALYSIS ---"
    )

    try:
        extras: ReportExtras = llm.invoke(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.error("report_generation_node failed: %s", exc)
        extras = ReportExtras(
            suggested_discovery_questions=[],
            suggested_outreach_strategy=ReportSection(
                content="Unavailable due to an internal error.",
                confidence="low",
            ),
            unknowns=unknown_topics,
        )

    report = StructuredReport(
        company_overview=ReportSection(**analysis.get("company_overview", {})),
        products_and_services=ReportSection(
            **analysis.get("products_and_services", {})
        ),
        target_customers=ReportSection(**analysis.get("target_customers", {})),
        business_signals=ReportSection(**analysis.get("business_signals", {})),
        risks_and_challenges=ReportSection(
            **analysis.get("risks_and_challenges", {})
        ),
        suggested_discovery_questions=extras.suggested_discovery_questions,
        suggested_outreach_strategy=extras.suggested_outreach_strategy,
        unknowns=extras.unknowns,
        sources=all_sources,
    )

    return {"final_report": report, "status": "Report complete"}
