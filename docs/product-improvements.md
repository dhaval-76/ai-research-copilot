# Product Improvements & Business Analysis

## 1. Product Weaknesses (Top 5)

1. **No auth/multi-tenancy.** Anyone with a session ID — or who simply
   calls `GET /sessions` — can read any session's report and chat
   history. There is no user or tenant concept anywhere in the system.
   This is disqualifying for any real sales-team deployment, where
   research and deal context are sensitive.
2. **No rate limiting on LLM or search calls.** Nothing stops a single
   user, script, or bug from exhausting Groq/Tavily quota or driving up
   cost. There's no per-user budget, no global throttle, no backoff
   beyond what the LangChain client does by default.
3. **Chat is not streaming.** Follow-up answers are request/response
   only; a longer answer renders all at once after a multi-second wait
   rather than appearing token-by-token, which reads as slower than it
   actually is.
4. **Research runs sequentially, including retries.** The five base
   research topics (plus an optional competitor-landscape task) run one
   at a time, and the gap-fill/quality-check retry loops add further
   sequential passes on top. A typical run takes roughly 60-90 seconds;
   a parallel fan-out across topics could plausibly cut that to
   15-20 seconds.
5. **No eval harness or quality telemetry.** There's no way to detect
   report quality regressions when a prompt or model changes, and no
   visibility into how often LLM structured-output fallbacks are
   triggering in practice (see `engineering-decisions.md`'s "Biggest
   Technical Risk"). Hallucination rate is effectively unmeasured.

## 2. Top 3 Improvements (Priority & Impact)

| Improvement | Timeline | Impact | Revenue |
|---|---|---|---|
| **Auth + RBAC** | 1 week | Unlocks any real (non-solo) deployment; enables per-user cost tracking | $0 → licensing revenue becomes possible at all |
| **Parallel research + streaming chat** | 2 weeks | ~4x faster runs (60-90s → 15-20s); better perceived chat latency | Supports a higher-tier, faster-response pricing tier |
| **Eval harness + fallback/cost telemetry** | 1.5 weeks | Confidence to iterate on prompts/models without silent quality regressions | Enterprise credibility, SLA readiness |

## 3. Market Sizing & Business Model

**Who buys:** Enterprise sales organizations and sales-enablement teams.
A back-of-envelope TAM: roughly 150K enterprise AE/SDR seats at a
plausible $500/year per-seat add-on price ≈ **$75M TAM** for direct
seat-based sales. A second channel: SMB upsell via white-labeling into
existing sales-enablement platforms (e.g. Highspot, Seismic) rather than
selling directly.

**Who uses it:** Individual sales reps and account executives preparing
for calls, plus sales managers reviewing rep prep quality before key
meetings. **Value drivers:** turning 2-3 hours of manual company research
into a 2-minute generated briefing; faster deal velocity from better-
prepared first calls; competitive intelligence surfaced automatically
rather than researched ad hoc.

**Pricing shape:** Freemium (a handful of sessions/month) → Pro
(~$49/month, individual) → Enterprise ($2K-5K/seat/year, with SSO,
admin controls, and usage analytics once auth exists to support them).

## 4. Success Metrics (6-Month Targets, if pursued commercially)

- Active users: 500 · NPS: >50 · Monthly churn: <5%
- Median run time: <20s · Hallucination/fallback rate: <5% ·
  Self-reported report quality: >8.0/10
- CAC: ~$150 · LTV: ~$1,200 · Sessions/month: ~2,000

These are directional targets for planning purposes, not validated
against real usage data — there is no production deployment or user base
behind this prototype yet.

## 5. Four-Week AI/Engineering Roadmap

- **Week 1:** Authentication (session-scoped at minimum, JWT-based),
  basic per-user rate limiting, and request-level cost/usage logging.
- **Week 2:** Parallel research fan-out via LangGraph's `Send` API,
  SSE-based chat streaming (reusing the workflow progress streaming
  pattern already built), and per-node telemetry (fallback rates, token
  usage, search-provider failure rates).
- **Week 3:** A fixed gold-standard eval set (e.g. 20 known companies
  with manually reviewed expected report quality), automated regression
  runs against it, and alerting on quality drops.
- **Week 4:** Report export (PDF), basic feature flags for safer
  rollout of the above, API documentation polish, general-availability
  prep.

## 6. Biggest Risks & Mitigations

| Risk | Mitigation |
|---|---|
| **Cost spiral** — Groq's free tier and Tavily's free tier both have caps; sustained real usage would exceed them quickly, and there's currently no per-user budget to prevent one user from consuming the whole allotment. | Per-user rate limiting; cache research findings by normalized company (already partially supported by the session-dedup model in `engineering-decisions.md` §5) so repeat lookups of the same company don't re-spend quota. |
| **Scaling** — the current connection pools (10 connections each for app DB and checkpoint DB) and single-backend-instance assumption would not hold up under meaningfully concurrent load. | Horizontal scaling behind a load balancer, read replicas for the app DB, and a distributed cache (e.g. Redis) for session-state coordination across instances. |
| **Reliability** — Groq and Tavily are both used on free/low tiers with no SLA; LLM structured-output adherence is not guaranteed across all models/load conditions. | Fallback LLM provider configuration (already provider-agnostic via `get_chat_model()`), eval-driven monitoring of fallback-trigger rates, and a human-review step for high-stakes/high-value research sessions. |

## 7. Feature to Reconsider

Earlier drafts of this document proposed removing chat history
persistence as low-value. On reflection, this is the wrong call: chat
history is now embedded directly in `GET /sessions/{id}` specifically to
*remove* a redundant fetch (see `engineering-decisions.md` §7), meaning
persisted chat is already cheap to serve and is part of the core "come
back to a session and pick up where you left off" experience. The
actual candidate for removal/simplification is the now-redundant
standalone `GET /sessions/{id}/chat` endpoint (kept only for direct
access, unused by the frontend) — a smaller, lower-stakes cleanup than
removing persistence itself.

## 8. Feature to Add

**Document/file ingestion for research grounding.** Sales reps often
already have a pitch deck, an RFQ, or a prior call transcript relevant
to the company being researched. Allowing upload of these as additional
context — extracted and fed into the `analyze` node alongside web
research — would ground reports in information that isn't publicly
searchable at all, and is a natural extension of the existing
research-and-synthesize architecture rather than a new system. Estimated
impact: meaningfully reduces manual cross-referencing time, and improves
report relevance for deals where the public web genuinely doesn't have
the answer (e.g. an RFQ's specific technical requirements).

## 9. First 90 Days (Phased, if pursued commercially)

- **Days 1-15:** Authentication, per-user rate limiting, usage/cost
  telemetry.
- **Days 16-30:** Parallel research fan-out, chat streaming, performance
  benchmarking against the pre-parallel baseline.
- **Days 31-45:** Eval harness, automated regression testing against the
  gold-standard set.
- **Days 46-60:** Pricing tiers, billing integration, closed beta with a
  small number of real sales teams.
- **Days 61-75:** Report export, document ingestion (feature 8), A/B
  testing infrastructure for prompt/model changes.
- **Days 76-90:** General availability, outbound sales motion, initial
  case studies from beta users.

## 10. Ownership Perspective — what I'd change first and why

If I owned this product, the very first change would be **authentication**,
not because it's the most interesting engineering problem, but because
it's the one gap that makes every other improvement moot — there is no
deployment of this product, however fast or accurate, that's
responsible to ship to real sales data without it. Everything else on
this list (speed, eval quality, document ingestion) compounds value on
top of a system that's actually safe to give to a second user.

After that, the order is roughly: make it fast enough that it beats
manually Googling a company (parallel research, streaming chat) — because
speed is the most legible, demoable value proposition to a sales rep
deciding whether to trust this over their own habits — then make it
provably accurate (eval harness) before scaling distribution, since
trust, once lost to a bad report in front of a real prospect, is
expensive to win back.

---

## Summary

**Technical foundation:** solid for a prototype — LangGraph workflow
with genuine conditional branching and bounded retries, Postgres-backed
persistence and checkpointing (with real recoverability, not just
in-memory state), Docker Compose deployment, a typed frontend contract,
and an SSE-based progress/resume model that handles real reconnect
scenarios correctly (see `engineering-decisions.md` §10 for a case
where this took real debugging to get right).

**What's missing before this could be a real product:** authentication,
rate limiting, automated testing/eval, and parallelized research. None
of these are architecturally blocked — the codebase is structured in a
way (provider-agnostic LLM/search, abstracted persistence, a documented
tech-debt list) that should make adding them additive rather than
requiring a rewrite.