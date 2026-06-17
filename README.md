# Zylabs AI Research Copilot

An AI-powered research copilot that helps prepare for sales or business
meetings. Give it a company, website, and an objective, and it runs a
LangGraph workflow that researches the company, analyzes findings, and
produces a structured briefing — overview, products, target customers,
business signals, risks, discovery questions, outreach strategy, and
unknowns. Follow-up questions are answered from the generated report.

```
Frontend (React + TypeScript)  →  Backend APIs (FastAPI)  →  LangGraph Workflow  →  PostgreSQL
                                                                     ↓
                                                              Web Search + LLM
```

See [`docs/architecture.md`](docs/architecture.md) for the full workflow
design (including all conditional edges and the resume/recoverability
model) and [`docs/engineering-decisions.md`](docs/engineering-decisions.md)
for the reasoning behind the current implementation, including what
changed and why across the project's iterations.

## Prerequisites

- Docker & Docker Compose (recommended — brings up the full stack
  including both Postgres instances)
- Or, for local non-Docker development: Python 3.12+, Node.js 18+, and
  a local PostgreSQL instance
- A free [Groq](https://console.groq.com) API key (LLM)
- A free [Tavily](https://tavily.com) API key (web search; recommended
  — `duckduckgo-search` is used as a fallback but is unreliable on some
  networks, see `engineering-decisions.md`)

## Running with Docker Compose (recommended)

```bash
cp backend/.env.example backend/.env
# edit backend/.env: add GROQ_API_KEY and TAVILY_API_KEY

docker compose up --build
```

This starts four services:

- `db` — primary Postgres instance (sessions, reports, chat, progress events)
- `checkpoint_db` — separate Postgres instance for LangGraph workflow checkpoints
- `backend` — FastAPI app on `http://localhost:8000`
- `frontend` — built React app served via nginx on `http://localhost:8080`

The backend's `DATABASE_URL` and `CHECKPOINT_DATABASE_URL` are overridden
inside `docker-compose.yml` to point at the compose service names (`db`,
`checkpoint_db`) on Postgres's internal container port `5432`, regardless
of what host-side ports you've mapped them to. See the comments in
`docker-compose.yml` if you change the port mappings.

## Hybrid development with Docker Compose

For active development, use `docker-compose.dev.yml` to bring up only the
Postgres services, and then run the backend and frontend natively.

```bash
docker compose -f docker-compose.dev.yml up -d
```

Then start the backend and frontend locally as described below. In
`backend/.env`, set `DATABASE_URL` and `CHECKPOINT_DATABASE_URL` to:

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/zylabs
CHECKPOINT_DATABASE_URL=postgresql://postgres:postgres@localhost:5434/zylabs_checkpoints
```

This keeps the database environment stable while letting you iterate on
backend and frontend code without rebuilding containers.

## Running locally without Docker

### Backend

```bash
cd backend
python3.12 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
# edit .env: GROQ_API_KEY, TAVILY_API_KEY, and DATABASE_URL /
# CHECKPOINT_DATABASE_URL pointing at your local Postgres instance(s)

uvicorn app.main:app --reload
```

Backend runs on `http://localhost:8000`. API docs (Swagger UI) at
`http://localhost:8000/docs`.

You'll need a running Postgres instance reachable at whatever
`DATABASE_URL` points to. Quickest way without installing Postgres
locally:

```bash
docker run --name zylabs-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=zylabs -p 5432:5432 -d postgres:16
```

`CHECKPOINT_DATABASE_URL` can point at the same database (it falls back
to `DATABASE_URL` if left unset) or a second instance if you want the
separation described in `engineering-decisions.md`.

### Quick CLI sanity check (optional)

Before running the full API, you can verify the LangGraph workflow runs
end-to-end on its own:

```bash
python -m scripts.test_graph
```

### Frontend

```bash
cd frontend
npm install

cp .env.example .env
# defaults to http://localhost:8000, change if backend runs elsewhere

npm run dev
```

Frontend runs on `http://localhost:5173`.

## Using it

1. Open the frontend. Create a research session: company name, website
   (required), and your objective (e.g. "Preparing for a sales call to
   pitch our fraud detection API"). All three together form a session's
   identity — submitting the same triple again reopens the existing
   session rather than creating a duplicate.
2. Click **Run research**. The workflow trace streams live as the graph
   moves through planning, research, analysis, quality checks, and
   report generation — including any gap-fill retries.
3. Once complete, the structured report appears with confidence levels
   and sources per section.
4. Use the chat panel to ask follow-up questions — answers are grounded
   in the report and rendered as markdown (including code blocks),
   and the copilot will say when something isn't covered rather than
   guessing.
5. If you refresh or lose connection mid-run, reopening the session
   resumes the workflow from its last completed step rather than
   restarting (see `engineering-decisions.md` for the resume logic and
   its edge cases).
6. Use **Regenerate report** on a completed session to clear its report,
   chat history, and checkpoint state and run it again from scratch.

## API surface

| Method | Path                        | Purpose                                                                                                                         |
| ------ | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `POST` | `/sessions`                 | Create a session, or return an existing one for the same normalized company/website/objective                                   |
| `GET`  | `/sessions`                 | List session history                                                                                                            |
| `GET`  | `/sessions/{id}`            | Session detail — includes report, persisted progress events, and chat history when available                                    |
| `GET`  | `/sessions/{id}/run`        | SSE stream that executes (or resumes) the LangGraph workflow, one event per node                                                |
| `POST` | `/sessions/{id}/regenerate` | Clear report/checkpoint/chat state and prepare the session for a fresh run                                                      |
| `POST` | `/sessions/{id}/chat`       | Ask a follow-up question, answered from the report                                                                              |
| `GET`  | `/sessions/{id}/chat`       | Chat history for the session (superseded for normal app use by `chat_messages` on `GET /sessions/{id}`; kept for direct access) |

Note: `GET /sessions/{id}/run` is a `GET`, not a `POST`, specifically
because the frontend uses the browser's native `EventSource` API for
SSE, which only supports `GET` requests.

## Project structure

```
backend/
  app/
    api/          # FastAPI routers (sessions, chat)
    core/         # config, db (app Postgres), checkpoint (workflow Postgres), search, LLM factory
    graph/        # LangGraph state, nodes, workflow, chat logic
    models/       # API request/response schemas
  scripts/        # CLI test script for the graph
  Dockerfile
frontend/
  src/
    components/   # Sidebar, SessionDetail, ReportView, ChatPanel, Badges, NotificationBanner, etc.
    lib/          # shared constants (node labels, styles, report section order)
    api.ts        # typed backend API client
    types.ts      # TypeScript types mirroring backend Pydantic schemas
  Dockerfile
  nginx.conf
docs/
  architecture.md
  engineering-decisions.md
  product-improvements.md
docker-compose.yml
```

## Configuration

All environment-specific values are read from `.env` files — see
`.env.example` in each directory. Notable backend variables:

- `LLM_PROVIDER` — `groq` (default) or `google`; swapping providers is
  a config change, not a code change (`app/core/config.py`)
- `GROQ_API_KEY` / `GOOGLE_API_KEY` — provider credentials
- `TAVILY_API_KEY` — if unset, falls back to `duckduckgo-search`
- `DATABASE_URL` — Postgres connection string for app data
- `CHECKPOINT_DATABASE_URL` — optional separate Postgres connection
  string for LangGraph checkpoints; falls back to `DATABASE_URL` if unset
- `MAX_RESEARCH_RETRIES` — bounds the gap-fill/quality-check retry loops
- `CORS_ORIGINS` — comma-separated list of allowed frontend origins

Frontend: `VITE_API_BASE_URL` (backend base URL; baked into the build
at compile time, since Vite env vars are not runtime-configurable).

## Known limitations / not yet implemented

This is a working prototype, not a production deployment. Notably
absent: authentication/authorization (the API is currently open),
automated tests, chat response streaming, LLM/search rate limiting, and
parallel research execution (topics run sequentially). See
`docs/engineering-decisions.md` for the full technical debt list and
`docs/product-improvements.md` for the roadmap these gaps feed into.
