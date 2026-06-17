# Architecture

## Overview

```
Frontend (React + TS)  →  Backend APIs (FastAPI)  →  LangGraph Workflow  →  PostgreSQL
                                                              ↓
                                                       Web Search + LLM
```

A research session is created via the backend API. Running it starts (or
resumes) a LangGraph workflow; progress streams to the frontend via
Server-Sent Events, and the final report is persisted in Postgres
alongside the session's metadata, chat history, and progress trace.

## Session identity and deduplication

A session's identity is the normalized triple of (company name, website,
objective) — all three are required at creation. `POST /sessions`
checks for an existing session with the same normalized inputs
(lowercased, trimmed, trailing slashes stripped from the website) before
creating a new one; if found, it returns the existing session rather
than starting duplicate research. This avoids burning LLM/search quota
re-researching the same company for the same stated purpose, and keeps
session history free of accidental duplicates from double-clicks or
repeated form submissions.

`POST /sessions/{id}/regenerate` exists for the case where the user
*does* want to rerun a completed session — it clears the report, chat
history, progress events, and LangGraph checkpoint for that session ID,
then resets its status to `pending` so the next `/run` call starts a
genuinely fresh execution.

## LangGraph Workflow

```
                 ┌─────────┐
                 │ planner │
                 └────┬────┘
                      │ (conditional #1: objective-driven)
        ┌─────────────┴─────────────┐
        │                            │
 ┌──────▼────────────┐         ┌─────▼─────┐
 │ competitor_research│ ──────► │  research  │ ◄────┐
 └────────────────────┘         └─────┬─────┘       │
                                       │ (conditional #2:       │
                                       │  data-richness check)  │
                             ┌─────────┴─────────┐              │
                             │                   │              │
                       ┌─────▼────┐        ┌─────▼──────┐       │
                       │ gap_fill │───────►│  analyze   │       │
                       └─────▲────┘        └─────┬──────┘       │
                             │                    │              │
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

(Note: the analysis node is registered as `"analyze"` in `workflow.py` —
`"analysis"` was avoided as a node name because it collides with the
`analysis` key already used in `GraphState`, which newer LangGraph
versions reject with `ValueError: 'analysis' is already being used as a
state key`.)

### Nodes

| Node | Responsibility |
|---|---|
| `planner` | Classifies the objective into a `research_mode` (sales / investment / competitive / general) and produces a topic-by-topic research plan |
| `competitor_research` | Reached only for investment/competitive objectives; adds a competitor-landscape task to the plan |
| `research` | Runs web searches for any plan topic not yet researched; scores each topic's confidence by result count |
| `gap_fill` | Broadens queries for low-confidence topics and clears them so `research` retries with simpler terms |
| `analyze` | Synthesizes raw findings into the five core report sections, with confidence carried through from the underlying data (not invented by the LLM) |
| `quality_check` | Flags low-confidence sections for one more targeted research pass |
| `report_generation` | Adds discovery questions, outreach strategy, and unknowns; compiles the final report and source list |

### Conditional Edges

1. **`planner` → `competitor_research` / `research`** — driven by `research_mode`. Investment and competitive analyses get an extra competitor-landscape task; sales/general objectives skip straight to research.
2. **`research` → `gap_fill` / `analyze`** — if a majority of topics came back with no/weak search results, do one broadened pass before analysis rather than analyzing on thin data.
3. **`quality_check` → `gap_fill` / `report_generation`** — if specific sections are still low-confidence after analysis, loop back for a targeted retry. Bounded by `max_retries` (default 1, configurable via `MAX_RESEARCH_RETRIES`) so a low-information company can't loop forever — it surfaces those gaps in `Unknowns` instead.

### Shared State

All nodes read/write a single `GraphState` (TypedDict): session inputs,
`research_plan`, `raw_research` (per-topic findings with confidence +
source URLs), `analysis` (per-section results), `quality_issues`,
`retry_count`, and `final_report`. Each node also sets a human-readable
`status` string, which is what the frontend's progress trace displays.

## Recoverability and resume

The compiled graph uses LangGraph's `PostgresSaver` as its checkpointer
(see `app/core/checkpoint.py`), backed by a `psycopg_pool.ConnectionPool`
rather than a single bare connection. Every node transition is persisted
to Postgres, keyed by `session_id` as the LangGraph `thread_id`.

This enables two distinct recovery scenarios:

- **Browser reconnect**: if the SSE connection drops (tab closed,
  network blip, page refresh) while a run is in progress, reopening the
  session and re-triggering `/run` resumes from the last completed node
  instead of restarting.
- **Backend restart**: because checkpoints are in Postgres (not
  in-memory or in a container-local SQLite file), a backend process
  restart does not lose in-progress workflow state either.

### Resume-detection: a real edge case

`GET /sessions/{id}/run` decides whether to resume or start fresh by
checking the session's stored `status` and the LangGraph checkpoint's
`next` field (which nodes are queued to run next). The naive version of
this check — `status == "running" and bool(graph_state.next)` — has a
real race: LangGraph commits a node's checkpoint and the "what's next"
routing decision as separate writes. For nodes with conditional outgoing
edges (e.g. `planner`, which branches to either `competitor_research` or
`research`), a reconnect landing in the narrow gap between these two
writes can read `next=()` even though the workflow is genuinely
mid-run — the checkpoint exists, but its `next` field hasn't been
populated by the routing write yet. Treating `next=()` as "finished" in
that gap would incorrectly restart a workflow from scratch even though a
checkpoint exists.

The fix: only treat a run as truly finished if `final_report` is present
in the checkpointed state (this only happens after `report_generation`,
the graph's last node before `END`). `next=()` without a `final_report`
present means "resume, the routing write just hasn't landed yet," not
"the workflow is done." A separate, narrower case — `status == "running"`
with *no checkpoint at all* — means the disconnect happened before the
very first superstep was ever committed (e.g. during the first node's
LLM call); there's nothing to resume, so the run restarts cleanly from
the initial state. See `app/api/sessions.py::run_session` and
`docs/engineering-decisions.md` for the full reasoning.

## Backend (FastAPI)

- **Session APIs** — create/reuse session, list history, get detail
  (report + progress trace + chat history), regenerate
- **Workflow Execution API** — `GET /sessions/{id}/run`, SSE stream that
  starts or resumes the graph and persists progress events as they occur
  (so the trace survives a reconnect even mid-run)
- **Chat APIs** — follow-up questions answered from `final_report` +
  `raw_research` context (no vector store needed at this scale)
- **Persistence** — Postgres for app data (`app/core/db.py`); a second,
  independently-configurable Postgres connection for LangGraph
  checkpoints (`app/core/checkpoint.py`)
- **Config** — all environment-specific values (LLM provider/keys,
  retry limits, both database URLs, CORS) via `app/core/config.py`,
  never hardcoded

### Why `GET`, not `POST`, for `/run`

The frontend uses the browser's native `EventSource` API to consume the
SSE stream, and `EventSource` only supports `GET` requests — there is no
way to attach a request body or use another HTTP method with it. This is
why workflow execution, which conceptually triggers an action (not just
reading a resource), is exposed as a `GET` endpoint.

## Data persistence

Two separate Postgres connections, independently configurable
(`DATABASE_URL` / `CHECKPOINT_DATABASE_URL`), so checkpoint storage
(higher write frequency, more disposable) can be scaled, pruned, or
hosted separately from app data (lower frequency, must not be lost):

- `sessions` — normalized input keys (for dedup), status, research mode, timestamps
- `reports` — final report stored as `JSONB`
- `chat_messages` — per-session chat history
- `progress_events` — persisted SSE trace, so a reconnect can replay
  the progress a user already saw before the disconnect
- LangGraph checkpoint tables — managed by `PostgresSaver` itself, not
  part of the app schema in `db.py`

See `docs/engineering-decisions.md` for the column type choices
(`TIMESTAMPTZ`, `CHECK` constraints in place of enums, `JSONB`, etc.)
and the SQLite-to-Postgres migration rationale.

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/sessions` | Create a session, or return an existing one for matching normalized inputs |
| `GET` | `/sessions` | List session history |
| `GET` | `/sessions/{id}` | Session detail — report, progress events, chat history |
| `GET` | `/sessions/{id}/run` | SSE stream — executes or resumes the LangGraph workflow |
| `POST` | `/sessions/{id}/regenerate` | Clear report/checkpoint/chat state, reset to `pending` |
| `POST` | `/sessions/{id}/chat` | Ask a follow-up question grounded in the report |
| `GET` | `/sessions/{id}/chat` | Chat history (now also embedded in `GET /sessions/{id}`; kept for direct access) |

## Frontend (React + TypeScript)

- Session creation form (company, website, objective — all required)
- Session history list
- Session detail page with live workflow progress (per-node trace,
  including gap-fill retries), resume/regenerate controls
- Structured report view (sectioned, with confidence badges and sources)
- Follow-up chat panel scoped to the report's context, with markdown
  and code-block rendering
- All node labels, report section labels/order, and styling are sourced
  from shared frontend constants (`src/lib/constants.ts`) rather than
  hardcoded inline in components — see `engineering-decisions.md` for
  the broader "no hardcoding, abstract business logic from UI" pass
- Fully typed via TypeScript, with `src/types.ts` mirroring the backend's
  Pydantic schemas as the explicit frontend/backend contract boundary

---
*Last updated to reflect the Postgres-backed persistence and checkpoint
model, Docker Compose deployment, TypeScript frontend, session
deduplication/regenerate, and the resume-detection race fix.*