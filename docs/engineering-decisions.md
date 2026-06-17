# Engineering Decisions

This document tracks the major engineering decisions made while building
the assignment, in roughly the order they happened, along with
alternatives considered and the tradeoffs accepted. Several entries
reflect real bugs hit during development rather than purely up-front
design choices — those are called out explicitly, since the debugging
trail is itself part of the engineering reasoning.

## 1. LangGraph workflow with bounded conditional retry loops

**Decision:** The research workflow has three conditional edges: an
objective-driven branch (competitor research for investment/competitive
objectives), a data-richness check after initial research, and a
quality-check retry loop after analysis. Both retry paths route through
a shared `gap_fill` node and are bounded by a single `retry_count` /
`max_retries` (default 1, via `MAX_RESEARCH_RETRIES`) shared across both
loops.

**Alternatives considered:**
- A linear `Planner -> Research -> Analysis -> Report` pipeline — the
  "single LLM call wrapped in an API" anti-pattern the assignment
  explicitly warns against.
- Unbounded retries until quality passes — rejected because a
  low-information company (e.g. a small private business with little
  online presence) could loop indefinitely or burn API quota for no
  gain.
- Separate retry counters per loop type — more "correct" but adds state
  complexity for marginal benefit at this scale.

**Tradeoff:** A shared, low retry budget means a session that needs
gap-filling in research *and* hits quality issues in analysis only gets
one combined retry, not one of each. In practice this means
under-researched topics surface honestly in `Unknowns` rather than the
system endlessly trying to manufacture a confident answer.

## 2. Node naming collision: `analysis` vs `analyze`

**Decision:** The analysis node is registered as `"analyze"` in
`workflow.py`, not `"analysis"`.

**What happened:** Initial implementation used `"analysis"` as the node
name, matching the `analysis` key already used in `GraphState`. A
LangGraph version upgrade (`0.2.39` → a newer patch pulled in by pip
since exact versions weren't pinned) started rejecting this with
`ValueError: 'analysis' is already being used as a state key` —
apparently newer LangGraph disallows node names that collide with
`StateGraph`'s schema keys, which earlier versions allowed.

**Fix:** Renamed the node to `"analyze"` everywhere it's registered and
referenced in conditional edge mappings (`workflow.py`). The
`analysis_node` function name and the `analysis` field in `GraphState`
were left unchanged, since only the *node identifier* collided, not the
underlying Python names.

**Lesson:** Library version drift between when code is written and when
it's actually installed (via loose `>=` version ranges) can surface
breaking behavior changes invisibly. This is also why several
dependencies in `requirements.txt` ended up as ranges rather than exact
pins — see entry 4.

## 3. Search provider: Tavily over duckduckgo-search

**Decision:** Web search is abstracted behind `core/search.py`, with
Tavily as the primary provider (used when `TAVILY_API_KEY` is set) and
DuckDuckGo as a fallback.

**What happened:** `duckduckgo-search` (via its `primp` HTTP backend)
failed with DNS resolution timeouts during development — confirmed via
direct testing that `socket.gethostbyname()` and `requests.get()` worked
fine on the same machine, while `primp.get()` specifically failed. This
isolated the issue to `primp` itself (a known recurring problem with
that library on certain macOS network configurations), not the network
or the application code.

**Alternatives considered:**
- Upgrading `duckduckgo-search`/`primp` to a newer version — tried as a
  cheap first step, but not treated as a blocking dependency since the
  underlying `primp` DNS issue has recurred across multiple versions of
  that library historically.
- Tavily, a search API purpose-built for LLM agents, built on standard
  `requests`/`httpx` (the same HTTP path already confirmed working).

**Tradeoff:** Tavily's free tier is capped at 1,000 searches/month. Each
research run uses roughly 5-8 searches, supporting on the order of
125-200 full research sessions/month on the free tier — fine for a
demo/evaluation, not for production scale. The provider stays abstracted
behind one function specifically so swapping or adding a paid provider
later doesn't touch node code.

## 4. Dependency version conflicts and the move to version ranges

**Decision:** Several `requirements.txt` entries use version ranges
(`>=x,<y`) rather than exact pins, specifically `langgraph`,
`langchain-core`, `langchain-groq`, `langchain-google-genai`.

**What happened:** `langgraph-checkpoint-sqlite==1.0.3` (pinned) depended
on `langgraph-checkpoint<2.0.0`, while the pinned `langgraph==0.2.39`
required `langgraph-checkpoint>=2.0.0` — an unresolvable conflict, and no
version of `langgraph-checkpoint-sqlite` satisfying the newer constraint
appeared to exist at the time. This blocked installation entirely.

**Fix (intermediate):** Dropped `langgraph-checkpoint-sqlite` and used
LangGraph's built-in in-memory `MemorySaver` as a temporary unblock,
deferring real persistence to the API/database layer. This was later
superseded entirely once the project moved to Postgres-backed
checkpointing (entry 8) — `MemorySaver` provided zero crash recovery,
which was an explicitly accepted, temporary gap at the time.

**Lesson:** exact pins across a fast-moving library ecosystem
(LangGraph/LangChain shipped multiple breaking releases during this
project's timeline) create more conflict risk than they prevent;
ranges plus testing the actual resolved versions caught issues faster.

## 5. Session deduplication and input normalization

**Decision:** A session's identity is the normalized triple (company
name, website, objective). `company_key` / `website_key` /
`objective_key` columns store lowercased, trimmed, slash-stripped
versions of the inputs, with a unique index enforcing one session per
normalized triple. `POST /sessions` looks up an existing session by
these keys before creating a new one.

**What happened / why this was added:** Without this, every accidental
double-submit or repeated "let me try this company again" produced a
brand new session and a brand new full research run — burning LLM and
search quota on work that had already been done, and cluttering session
history with near-duplicates differing only in casing or a trailing
slash on the website.

**Alternatives considered:**
- Dedup by company name only — too weak, since the same company
  researched for a different objective should be a distinct session.
- No dedup, rely on the user to notice and avoid duplicates — rejected
  given how easy it is to accidentally double-submit a form.

**Companion decision — `regenerate`:** Because dedup means resubmitting
identical inputs reopens the existing session rather than creating a new
one, an explicit `POST /sessions/{id}/regenerate` endpoint was added for
the case where a user genuinely wants to rerun research (e.g. they
believe the company's situation changed, or want a fresh attempt after a
weak first run). It clears the report, chat history, progress events,
and LangGraph checkpoint for that session ID and resets status to
`pending`.

**Also required:** website was changed from optional to a required input
on `SessionCreateRequest`, since `website` is part of the identity key —
an optional, frequently-blank field would have made the dedup key far
weaker (most sessions would key off `company_key` + `objective_key`
alone, with an empty `website_key`).

## 6. Progress events persisted, not just streamed

**Decision:** Each SSE event emitted during a workflow run is also
written to a `progress_events` table, keyed by session.
`GET /sessions/{id}` returns the full persisted trace as
`progress_events`.

**What happened / why:** Initially, workflow progress only existed as
SSE events in-flight — if the browser tab was closed or refreshed mid-run
and reopened, the frontend had no way to show what had already happened
before the reconnect; it would either show a blank trace or have to
guess. Persisting each event as it's emitted means reopening a session
mid-run (or after it completes) can render the full trace immediately
from `GET /sessions/{id}`, with `GET /sessions/{id}/run` only needed to
continue receiving *new* events.

**Tradeoff:** One extra DB write per node transition. Negligible at this
scale; would need batching or a lighter-weight store (e.g. Redis) if
research workflows became extremely high-frequency.

## 7. Chat history embedded in session detail (de-duplicated fetch)

**Decision:** `GET /sessions/{id}` now returns `chat_messages` directly
as part of the session detail payload.

**What happened:** Before this change, opening a session triggered
`GET /sessions/{id}` followed by a *separate* `GET /sessions/{id}/chat`
call from the frontend to populate the chat panel — observed directly in
logs as two near-simultaneous requests for the same session. Folding
`chat_messages` into the session detail response removes that redundant
round-trip; the standalone `GET /sessions/{id}/chat` endpoint still
exists (kept for direct/programmatic access and because `POST
/sessions/{id}/chat` still needs a corresponding read endpoint
conceptually), but is no longer called by the frontend in the normal
session-open flow.

**Tradeoff / remaining tech debt:** the standalone `GET` chat endpoint is
now effectively redundant for the app's own usage. It hasn't been
removed, since removing a documented endpoint felt like a separate
decision from deduplicating a fetch; see Top Technical Debt Items below.

## 8. Database type design (SQLite phase)

**Decision (superseded by entry 9, kept for the record):** While still
on SQLite, the schema was reworked from "almost everything is TEXT" to:
`created_at`/`updated_at` as `INTEGER` Unix epoch (SQLite has no native
timestamp type; epoch integers sort and range-query correctly, unlike
ISO strings, which only sort correctly if formatting is perfectly
consistent), `CHECK` constraints enforcing the allowed values for
`status`, `research_mode`, and `role` (SQLite has no enum type), and
`done` (progress events) as `INTEGER` 0/1 with an explicit `CHECK`.

**What happened (bug along the way):** The timestamp migration
originally tried to update rows via SQLite's implicit `rowid`. This
broke for `chat_messages` and `progress_events`, both of which declare
`id INTEGER PRIMARY KEY AUTOINCREMENT` — a declaration that makes `id`
itself an alias for `rowid`, which caused inconsistent row-factory
behavior (`IndexError: No item with that key` when accessing
`row["rowid"]`). Fixed by updating each table via its actual declared
primary key column instead of relying on `rowid` at all.

**Note:** This entire entry describes the SQLite-era version of the
schema. The project has since migrated to Postgres (entry 9), which
uses native `TIMESTAMPTZ`, `BOOLEAN`, and `JSONB` types instead of these
SQLite workarounds. Keeping this entry because the *reasoning* about
why TEXT-everywhere is a problem, and why CHECK constraints matter,
carried forward unchanged into the Postgres schema.

## 9. Migration from SQLite to PostgreSQL (app data, then checkpoints)

**Decision:** Both the primary application database and the LangGraph
checkpoint store were migrated from SQLite to PostgreSQL, in two
separate steps (app data first, checkpoints second).

**Why:** SQLite's single-writer-at-a-time model and file-based storage
don't suit a backend that may run under any real concurrency, restart,
or be deployed beyond a single local process. This was explicitly
called out as a "top technical debt item" before being addressed.
Postgres also provides real types (`TIMESTAMPTZ`, `BOOLEAN`, `JSONB`)
in place of SQLite's TEXT-everything affinity system, carrying forward
the type-correctness work from entry 8 onto a backend actually suited
to it.

**App data migration:** `app/core/db.py` rewritten to use `psycopg`
(v3) with a `ConnectionPool`, plain SQL (no ORM, consistent with the
original design), `%s` placeholders, and native Postgres types:
`TIMESTAMPTZ` for timestamps (no more manual epoch conversion),
`BOOLEAN` for `done`, `JSONB` for `report_json` (psycopg
auto-serializes/deserializes dicts), and `CHECK` constraints retained
for `status`/`research_mode`/`role` (Postgres has a native `ENUM` type
too, but `CHECK` was kept since it's simpler to extend without a schema
migration when new values are added).

**Checkpoint migration — first attempt and its failure:** The first
implementation used `PostgresSaver.from_conn_string()`'s context-manager
pattern, manually entering the context (`ctx.__enter__()`) to keep a
single long-lived connection open for the process lifetime — mirroring
how the prior `SqliteSaver` held one connection. This failed in
practice: under FastAPI's request lifecycle, the connection closed
unexpectedly, surfacing as `psycopg.OperationalError: the connection is
closed` on `delete_thread()` calls (hit via the `/regenerate` endpoint,
but would have affected `/run` too).

**Checkpoint migration — fix:** Replaced the single bare connection with
a `psycopg_pool.ConnectionPool` passed directly to `PostgresSaver`,
matching the pattern already used for the app DB. Pool configured with
`autocommit=True` (PostgresSaver manages its own transaction boundaries
per operation; without autocommit, operations could get stuck inside an
uncommitted transaction) and `prepare_threshold=0` (disables psycopg's
prepared-statement caching, which doesn't play well with how
`PostgresSaver` reuses connections across operations — this is called
out in that library's own documentation).

**Separate checkpoint database:** After the pool fix was confirmed
working, the checkpoint store was further split onto its own Postgres
connection string (`CHECKPOINT_DATABASE_URL`, distinct from
`DATABASE_URL`, falling back to it if unset via
`Settings.resolved_checkpoint_database_url`). Checkpoint writes are
higher-frequency (per graph node) than app writes, and checkpoint data
is more disposable — a session remains usable even if its checkpoint
history were pruned or lost, whereas losing report/chat data would not
be acceptable. Splitting the two stores means they can be scaled, backed
up, or hosted independently at deployment time.

**Tradeoff:** Two Postgres instances (in Docker Compose: two separate
`postgres` services, `db` and `checkpoint_db`) instead of one increases
local dev and deployment complexity. Accepted because the operational
characteristics of the two stores are genuinely different, and the
config-driven fallback means single-Postgres local dev still works by
simply leaving `CHECKPOINT_DATABASE_URL` unset.

## 10. Resume-detection race condition

**Decision:** `GET /sessions/{id}/run`'s decision to resume vs. restart
checks for the presence of `final_report` in the checkpointed state,
not merely whether the checkpoint's `next` field is empty.

**What happened:** The original check was
`status == "running" and bool(graph_state.next)`. Manual testing (two
consecutive browser refreshes on the same in-progress session) produced
inconsistent results: one refresh correctly resumed
(`next=('competitor_research',)`), the very next refresh did not
(`next=()`), despite the session genuinely not being finished — borne
out by the *following* refresh resuming correctly into
`competitor_research`, an early node.

**Root cause:** LangGraph commits a node's checkpoint and the
"what's next" routing resolution as separate writes. This matters
specifically for nodes with conditional outgoing edges — `planner`
being the relevant one here, since it branches to either
`competitor_research` or `research` depending on `research_mode`. A
reconnect landing in the narrow window between the `planner` checkpoint
commit and its routing-decision commit reads a checkpoint with
`next=()`, which is indistinguishable, under the original check, from
the graph having actually finished.

**Fix:** Added a `has_final_report` check
(`"final_report" in graph_state.values`) as the authoritative signal for
"the workflow is actually done" — `final_report` is only ever written by
`report_generation`, the graph's last node before `END`. `next=()`
without a `final_report` present now means "checkpoint exists, resume
it" rather than "finished, restart." A third branch handles `status ==
"running"` with *no checkpoint at all* (disconnect occurred before the
very first superstep committed, e.g. mid-LLM-call on the first node) by
restarting cleanly, since there is genuinely nothing to resume from in
that case. Verbose logging was added at each branch specifically to
make this diagnosable from `docker compose logs` without needing to
reproduce in a debugger.

**Tradeoff:** This is still not a perfect signal under all possible
race conditions (e.g. extremely rare timing around the
`report_generation` checkpoint write itself), but it closes the
specific, reproducible gap found during testing, and the underlying
mechanism (separate checkpoint/routing commits) means *some* residual
race window is inherent to how LangGraph's Postgres checkpointer works
today, not something fully closable from the application layer alone.

## 11. Chat rendering as markdown with syntax highlighting

**Decision:** The chat panel renders assistant messages via
`react-markdown` + `remark-gfm` (tables, strikethrough, etc.) +
`react-syntax-highlighter` for fenced code blocks, instead of raw text.

**Why:** LLM responses naturally include lists, emphasis, and
occasionally code or structured data; rendering them as plain text
left formatting markers (`**`, `-`, etc.) visible verbatim, which reads
as broken rather than intentional.

**Tradeoff:** Two extra frontend dependencies
(`react-syntax-highlighter` also pulls in language grammar definitions,
increasing bundle size somewhat). Accepted given how directly it affects
perceived answer quality.

## 12. TypeScript conversion

**Decision:** The entire frontend was converted from JavaScript
(`.jsx`/`.js`) to TypeScript (`.tsx`/`.ts`), with a dedicated
`src/types.ts` mirroring the backend's Pydantic schemas
(`StructuredReport`, `ReportSection`, `SessionSummary`, etc.) as an
explicit contract boundary.

**Why:** At a single-developer, single-session prototype scale, plain
JS would have been sufficient. The conversion was made specifically
because this project is meant to demonstrate readiness for a
multi-engineer, evolving codebase — type-checking the API contract
means a backend field rename or removal surfaces as a compile error in
every frontend file that touches it, rather than a runtime `undefined`
discovered by a user.

**Tradeoff:** Slightly more setup (`tsconfig.json`, `vite-env.d.ts`,
typed props on every component) for no runtime behavior change. Accepted
as a one-time cost given the stated goal.

## 13. No hardcoding at the frontend; abstracted business logic and theming

**Decision:** Workflow node display labels and report section
labels/ordering live in shared frontend constants
(`src/lib/constants.ts`), not inline in components; theming (badge
color tokens for confidence/status) is similarly centralized rather than
duplicated per component; data-fetching and stream-handling logic is
kept in dedicated functions (`api.ts`) rather than mixed into component
bodies.

**Why:** Several of the early component drafts had node-label maps and
color logic written directly inside `WorkflowProgress.tsx`/`Badges.tsx`.
This works but means the *same* mapping (e.g. "what does the
`gap_fill` node look like in the UI") could drift if touched in two
places, and ties presentation concerns to wherever a component happens
to need them.

**Tradeoff:** A small amount of indirection (importing from
`constants.ts` rather than inlining a literal) for files that are
genuinely small enough that inlining wouldn't have caused real problems
at this project's current size. Worth it as the codebase grows past a
single contributor, which is the explicit lens this was evaluated
under.

## 14. Docker Compose for local full-stack development

**Decision:** `docker-compose.yml` brings up four services: `db`
(primary Postgres), `checkpoint_db` (separate Postgres for LangGraph
checkpoints, matching entry 9's split), `backend` (FastAPI), and
`frontend` (Vite build served via nginx).

**What happened (port confusion bug):** After remapping the host-side
ports for `db`/`checkpoint_db` (e.g. `5433:5432`, `5434:5432`) to avoid
colliding with a local Postgres install, the backend's `DATABASE_URL`/
`CHECKPOINT_DATABASE_URL` were updated to use the *host* ports
(`5433`/`5434`) — which broke container-to-container connectivity
(`Connection refused` to `172.18.0.3:5434`). The fix: Docker's
`HOST:CONTAINER` port mapping only changes the host-side port; every
container on the compose network still reaches Postgres on its
internal, unmapped port `5432`, regardless of what the host mapping
says. `docker-compose.yml`'s `backend.environment` block hardcodes
`db:5432` / `checkpoint_db:5432` specifically to avoid this becoming a
recurring trap, with an explicit comment at each port mapping.

**Frontend build-time vs. runtime config:** `VITE_API_BASE_URL` is
baked into the static JS bundle at build time (Vite env vars are
compile-time, not runtime-readable), passed via a Docker build arg.
This means changing the backend URL for a deployed frontend requires
rebuilding the frontend image, not just changing an environment
variable on a running container — a real constraint of static-site
deployments worth calling out explicitly rather than discovering later.

**Tradeoff:** Running two Postgres containers locally is heavier than
one, and the dual-host-port setup is a recurring source of the kind of
mixup described above. Accepted because it makes the Docker Compose
topology actually mirror the application/checkpoint database split
described in entry 9, rather than only existing as a config option
nobody locally exercises.

---

## Top Technical Debt Items

1. **No automated tests** — no backend unit tests, no frontend
   integration tests, no eval harness for report quality. The
   `scripts/test_graph.py` CLI script and manual curl/browser testing
   were the only verification methods used throughout development.
2. **No authentication/authorization** — the API is fully open. Anyone
   with a session ID (or who lists `/sessions`) can read any session's
   report and chat history. No user or tenant concept exists.
3. **Redundant `GET /sessions/{id}/chat` endpoint** — superseded for the
   app's own use by `chat_messages` embedded in `GET /sessions/{id}`
   (entry 7), but not removed; still documented as available.
4. **Chat has no streaming** — follow-up answers are request/response,
   not token-streamed; longer answers feel slower than necessary.
5. **No LLM/search rate limiting** — no per-user or global throttling on
   Groq or Tavily calls beyond LangChain's default retry behavior; a
   misbehaving client or traffic spike could exhaust API quota or incur
   unexpected cost.
6. **Sequential, not parallel, research** — the five research topics
   (plus the optional competitor-landscape task) run one after another.
   LangGraph's `Send` API would allow a parallel fan-out, meaningfully
   reducing run time.
7. **String literals instead of enums in places** — `research_mode`,
   `status`, `role`, and node names are plain strings validated only by
   `Literal` types (Pydantic) or `CHECK` constraints (Postgres), not a
   shared enum type used consistently across backend, DB, and frontend.
   Workable today but a source of potential drift as more values are
   added.
8. **Resume-detection residual race window** — see entry 10's tradeoff;
   the fix closes the specific reproduced bug but the underlying
   separate-commit behavior in LangGraph's Postgres checkpointer means
   some theoretical race window remains.
9. **No pruning of abandoned sessions/checkpoints** — failed or
   abandoned sessions accumulate progress events and checkpoint history
   indefinitely.
10. **Single-instance assumption** — the backend is not designed for
    multiple replicas (e.g. no distributed locking around session
    status transitions); running more than one backend instance against
    the same databases could race on the same session.

## Biggest Technical Risk

**LLM structured-output reliability under provider variability.** The
workflow leans on `with_structured_output()` for the planner, analysis,
and report-generation nodes. This has worked reliably in testing with
Groq's Llama 3.3 70B, but structured-output adherence varies across
models and can degrade under provider-side load, rate limiting, or with
cheaper/smaller models. Each node has a try/except fallback to keep the
graph from crashing outright, but a fallback firing frequently in
production would silently degrade report quality rather than surfacing
as an outright failure — and there is currently no telemetry tracking
how often fallbacks trigger, which is the gap an eval harness (entry 1
above, and the product roadmap) is meant to close.

## Near-term roadmap (if continuing)

1. Add an eval harness: run the workflow against a fixed set of known
   companies, score report completeness/groundedness, and track
   regressions when prompts or models change.
2. Add authentication (session-scoped at minimum) and basic
   per-user rate limiting before any wider exposure.
3. Stream chat responses token-by-token via SSE, reusing the same
   event-streaming pattern already built for workflow progress.
4. Implement parallel research fan-out via LangGraph's `Send` API.
5. Add automated tests for graph nodes (with mocked LLM/search calls)
   and for the API's session lifecycle (create → run → regenerate).
6. Decide on and execute removing or repurposing the redundant
   `GET /sessions/{id}/chat` endpoint (debt item 3).