# Architecture

## Overview

The AI Research Copilot has three layers:

```
Frontend (React)  →  Backend APIs (FastAPI)  →  LangGraph Workflow  →  Storage (SQLite)
                                                        ↓
                                                  Web Search + LLM
```

A research session is created via the API, which kicks off a LangGraph
run. Progress is streamed back to the frontend as the graph moves
through nodes. Once complete, the structured report is persisted and
available for follow-up chat.

## LangGraph Workflow

```
                 ┌─────────┐
                 │ planner │
                 └────┬────┘
                      │ (conditional #1: objective-driven)
        ┌─────────────┴─────────────┐
        │                            │
 ┌──────▼───────────┐          ┌─────▼─────┐
 │ competitor_research│ ─────► │  research  │ ◄────┐
 └────────────────────┘        └─────┬─────┘       │
                                      │ (conditional #2:      │
                                      │  data-richness check) │
                            ┌─────────┴─────────┐             │
                            │                   │             │
                      ┌─────▼────┐        ┌─────▼──────┐      │
                      │ gap_fill │───────►│ analysis   │      │
                      └─────▲────┘        └─────┬──────┘      │
                            │                    │             │
                            │              ┌─────▼────────┐    │
                            │              │ quality_check│    │
                            │              └─────┬────────┘    │
                            │   (conditional #3: bounded retry) │
                            └────────────────────┴─────────────┘
                                                   │
                                          ┌────────▼─────────┐
                                          │ report_generation│
                                          └────────┬─────────┘
                                                    │
                                                   END
```

### Nodes

| Node | Responsibility |
|---|---|
| `planner` | Classifies the objective into a `research_mode` (sales / investment / competitive / general) and produces a topic-by-topic research plan |
| `competitor_research` | Reached only for investment/competitive objectives; adds a competitor-landscape task to the plan |
| `research` | Runs web searches for any plan topic not yet researched; scores each topic's confidence by result count |
| `gap_fill` | Broadens queries for low-confidence topics and clears them so `research` retries with simpler terms |
| `analysis` | Synthesizes raw findings into the five core report sections, with confidence carried through from the underlying data (not invented by the LLM) |
| `quality_check` | Flags low-confidence sections for one more targeted research pass |
| `report_generation` | Adds discovery questions, outreach strategy, and unknowns; compiles the final report and source list |

### Conditional Edges

1. **`planner` → `competitor_research` / `research`** — driven by `research_mode`. Investment and competitive analyses get an extra competitor-landscape task; sales/general objectives skip straight to research.
2. **`research` → `gap_fill` / `analysis`** — if a majority of topics came back with no/weak search results, do one broadened pass before analysis rather than analyzing on thin data.
3. **`quality_check` → `gap_fill` / `report_generation`** — if specific sections are still low-confidence after analysis, loop back for a targeted retry. Bounded by `max_retries` (default 1) so a low-information company can't loop forever — it simply surfaces those gaps in `Unknowns` instead.

### Shared State

All nodes read/write a single `GraphState` (TypedDict): session inputs, `research_plan`, `raw_research` (per-topic findings with confidence + source URLs), `analysis` (per-section results), `quality_issues`, `retry_count`, and `final_report`. Intermediate state (plan, raw research, analysis) is what the frontend's progress UI streams.

### Recoverability

The graph is compiled with `SqliteSaver` as a checkpointer, keyed by `session_id` as the LangGraph `thread_id`. Every node transition is persisted, so:
- A crashed/restarted backend can resume a session from its last completed node, not from scratch.
- This checkpoint store doubles as the workflow-output persistence layer required by the spec.

## Backend (FastAPI)

- **Session APIs** — create session, list session history, get session detail
- **Workflow Execution APIs** — trigger graph run, stream progress (SSE)
- **Chat APIs** — follow-up questions answered from `final_report` + `raw_research` context (no vector store needed at this scale)
- **Persistence** — SQLite for session metadata + report storage; SQLite (separate file) for LangGraph checkpoints
- **Config** — all environment-specific values (LLM provider/keys, retry limits, search result counts) via `app/core/config.py`, never hardcoded

## LLM Provider

Provider-agnostic via `get_chat_model()` — defaults to Groq (free tier, fast) for development. Swapping to OpenAI/Anthropic/Gemini for production is a config change, not a code change.

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/sessions` | Create a research session (company, website, objective) |
| `GET` | `/sessions` | List session history |
| `GET` | `/sessions/{id}` | Session detail, including report once complete |
| `GET` | `/sessions/{id}/run` | SSE stream — executes the LangGraph workflow, one event per node, final event carries the report |
| `POST` | `/sessions/{id}/chat` | Ask a follow-up question (answered from the report) |
| `GET` | `/sessions/{id}/chat` | Chat history for the session |

`/sessions/{id}/run` is the core "Workflow Execution API" + "Workflow Progress UI" requirement — the frontend opens this with `EventSource` and renders each `{node, status}` event as it arrives.

## Frontend (React)

- Session creation form (company, website, objective)
- Session history list
- Session detail page with live workflow progress (per-node status)
- Structured report view (sectioned, with confidence badges and sources)
- Follow-up chat panel scoped to the report's context

---
*This document will be expanded as the build progresses (API contracts, DB schema, deployment notes).*
