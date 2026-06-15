# Engineering Decisions

## 1. LangGraph workflow with bounded conditional retry loops

**Decision:** The research workflow has three conditional edges: an
objective-driven branch (competitor research for investment/competitive
objectives), a data-richness check after initial research, and a
quality-check retry loop after analysis. Both retry paths route through
a shared `gap_fill` node and are bounded by a single `retry_count` /
`max_retries` (default 1) shared across both loops.

**Alternatives considered:**
- A linear `Planner -> Research -> Analysis -> Report` pipeline (the
  "single LLM call wrapped in an API" anti-pattern the spec explicitly
  warns against).
- Unbounded retries until quality passes -- rejected because a
  low-information company (e.g. a small private business with little
  online presence) could loop indefinitely or burn API quota for no
  gain.
- Separate retry counters per loop type -- more "correct" but adds
  state complexity for marginal benefit at this scale.

**Tradeoff:** A shared, low retry budget means a session that needs
gap-filling in research *and* hits quality issues in analysis only
gets one combined retry, not one of each. In practice this means
under-researched topics surface honestly in `Unknowns` rather than
the system endlessly trying to manufacture a confident answer --
which is the more honest behavior for a sales-prep tool anyway.

## 2. Split persistence: SqliteSaver (workflow checkpoints) + SQLite (session metadata)

**Decision:** LangGraph checkpointing uses `SqliteSaver` from
`langgraph-checkpoint-sqlite`, persisting per-node state to a dedicated
SQLite file (`CHECKPOINT_DB_PATH`). Durable session metadata and final
reports live in a separate plain SQLite layer (stdlib `sqlite3`, no ORM).

**Alternatives considered:**
- `MemorySaver` (in-process only) -- loses in-progress runs on restart.
- `PostgresSaver` -- heavier ops for a single-instance demo.
- Upgrading to `langgraph-checkpoint-sqlite` 3.x -- requires bumping
  `langgraph` past 0.2.x due to a `langgraph-checkpoint` version split;
  deferred until a broader dependency upgrade.

**Tradeoff:** Two SQLite files instead of one shared store. Checkpoint
tables are owned by LangGraph and not queried by app code directly, so
keeping them separate avoids schema coupling. `SqliteSaver` is
synchronous and not ideal for high concurrency, but is fine for this
single-worker demo.

## 3. Search provider: Tavily over duckduckgo-search

**Decision:** Web search is abstracted behind `core/search.py`, with
Tavily as the primary provider (used when `TAVILY_API_KEY` is set) and
DuckDuckGo as a fallback.

**Alternatives considered:**
- `duckduckgo-search` only (free, no signup) -- this was the initial
  choice for zero-friction setup.
- During development, `duckduckgo-search` (via its `primp` HTTP
  backend) failed with DNS resolution timeouts on macOS, while
  `requests`/`socket` worked fine on the same machine -- isolated to
  `primp` itself, not the network. Tavily (built on standard
  `requests`/`httpx`) was adopted as primary; DDG remains as a
  no-key fallback for environments where it does work.

**Tradeoff:** Tavily's free tier is capped at 1,000 searches/month.
Each research run uses ~5-8 searches, so this supports roughly
125-200 full research sessions/month on the free tier -- fine for
a demo/evaluation, but a production deployment would need a paid
tier or a different provider, which is why the provider stays
abstracted behind one function.

---

## Top Technical Debt Items

1. **Stale checkpoint cleanup** -- abandoned `running` sessions leave rows
   in the checkpoint DB until manually cleared; no TTL or sweeper yet.
2. **No automated tests** -- given the 3-day scope, testing was manual
   (the `scripts/test_graph.py` CLI script + curl against the API).
   Node functions are pure-ish (`state -> partial state`) and should be
   straightforward to unit test with mocked LLM/search calls.
3. **SQLite for everything** -- fine for a single-instance demo;
   would not handle concurrent writers well under real load.
4. **Chat has no streaming** -- follow-up answers are request/response,
   not token-streamed, so longer answers feel slower than they need to.
5. **No rate-limit-aware backoff beyond LangChain's defaults** -- under
   sustained load against Groq's free tier, requests could start
   failing with 429s with no app-level queuing/backoff.

## Biggest Technical Risk

**LLM structured-output reliability at scale.** The workflow leans on
`with_structured_output()` for the planner, analysis, and report-extras
nodes. This works reliably in testing with Groq's Llama 3.3 70B, but
structured-output adherence varies across models and can degrade under
provider-side load or with smaller/cheaper models. Each node has a
try/except fallback to keep the graph from crashing, but a fallback
that fires frequently in production would mean degraded report quality
rather than an outright failure -- which could go unnoticed without
monitoring on fallback-trigger rates.

## With 2 More Weeks

1. Add a small eval harness: run the workflow against ~20 known
   companies, score report quality (completeness, source validity,
   hallucination rate) to catch regressions when prompts change.
2. Stream chat responses token-by-token via SSE (same pattern as
   workflow progress).
3. Add the parallel research fan-out (LangGraph `Send` API) discussed
   during design -- run the 5 research topics concurrently instead of
   sequentially, cutting run time significantly.
4. Add lightweight monitoring: log fallback-trigger rates per node,
   token usage per run, and search-provider failure rates.