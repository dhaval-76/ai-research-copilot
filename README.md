# Zylabs AI Research Copilot

An AI-powered research copilot that helps prepare for sales/business
meetings: give it a company, website, and your objective, and it runs a
LangGraph workflow that researches the company, analyzes findings, and
produces a structured briefing — overview, products, target customers,
business signals, risks, discovery questions, outreach strategy, and
unknowns. You can then ask follow-up questions grounded in the report.

```
Frontend (React)  →  Backend APIs (FastAPI)  →  LangGraph Workflow  →  Storage (SQLite)
                                                        ↓
                                                  Web Search + LLM
```

See [`docs/architecture.md`](docs/architecture.md) for the full workflow
design (including the three conditional edges) and
[`docs/engineering-decisions.md`](docs/engineering-decisions.md) for key
decisions and tradeoffs.

## Prerequisites

- Python 3.12+
- Node.js 18+
- A free [Groq](https://console.groq.com) API key (LLM)
- A free [Tavily](https://tavily.com) API key (web search, recommended —
  see `engineering-decisions.md` for why)

## Backend setup

```bash
cd backend
python3.12 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
# edit .env: add GROQ_API_KEY and TAVILY_API_KEY

uvicorn app.main:app --reload
```

Backend runs on `http://localhost:8000`. API docs (Swagger UI) at
`http://localhost:8000/docs`.

### Quick CLI sanity check (optional)

Before running the full API, you can verify the LangGraph workflow runs
end-to-end on its own:

```bash
python -m scripts.test_graph
```

## Frontend setup

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
   (optional), and your objective (e.g. "Preparing for a sales call to
   pitch our fraud detection API").
2. Click **Run research**. The workflow trace streams live as the graph
   moves through planning, research, analysis, quality checks, and
   report generation — including any gap-fill retries.
3. Once complete, the structured report appears with confidence levels
   and sources per section.
4. Use the chat panel to ask follow-up questions — answers are grounded
   in the report, and the copilot will say when something isn't covered
   rather than guessing.

## Project structure

```
backend/
  app/
    api/          # FastAPI routers (sessions, chat)
    core/         # config, db, search, LLM factory
    graph/        # LangGraph state, nodes, workflow, chat logic
    models/       # API request/response schemas
  scripts/        # CLI test script for the graph
frontend/
  src/
    components/   # Sidebar, SessionDetail, ReportView, ChatPanel, etc.
    lib/          # shared constants (labels, styles)
    api.ts        # backend API client
docs/
  architecture.md
  engineering-decisions.md
  product-improvements.md
```

## Configuration

All environment-specific values are read from `.env` (backend) and
`.env` (frontend) — see `.env.example` in each directory. Notably:

- `LLM_PROVIDER` — `groq` (default) or `google`; swapping providers is a
  config change, not a code change (`app/core/config.py`)
- `TAVILY_API_KEY` — if unset, falls back to `duckduckgo-search` (less
  reliable on some networks)
- `MAX_RESEARCH_RETRIES` — bounds the gap-fill/quality-check retry loops