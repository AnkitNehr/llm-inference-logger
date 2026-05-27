# Architecture Notes

> A walk-through of how this system is built, why each piece exists, and what happens when things break.
> Companion to [README.md](./README.md) (setup + tradeoffs) and [k8s/README.md](./k8s/README.md) (deployment).

---

## 1. System Topology

Six independently-deployable services connected by HTTP, SSE, and a Redis Stream event bus.

```
                                                Browser
                                                   │
                                ┌──────────────────┼──────────────────┐
                                │ HTTP             │ SSE              │ HTTP
                                │ /conversations   │ /messages stream │ /stats
                                ▼                  ▼                  ▼
                            ╭───────────────────────────────╮   ╭──────────────╮
                            │       Chatbot API             │   │ Ingestion API│
                            │  ┌─────────────────────────┐  │   │              │
                            │  │ SDK wrapper (LLMClient) │──┼───┼─► POST /logs │   (async, non-blocking)
                            │  │  • providers: openai/   │  │   │              │
                            │  │    anthropic/gemini/mock│  │   │  validates   │
                            │  │  • PII redaction        │  │   │  ↓ XADD      │
                            │  │  • TTFT + token capture │  │   └──────┬───────┘
                            │  └────────┬────────────────┘  │          │
                            │           │ provider HTTP     │          │
                            │           ▼                   │          ▼
                            │  ╔═════════════════════╗      │   ╔══════════════╗
                            │  ║ OpenAI / Anthropic  ║      │   ║ Redis Stream ║
                            │  ║   / Gemini / Mock   ║      │   ║ inference_   ║
                            │  ╚═════════════════════╝      │   ║   logs       ║
                            │                               │   ╚══════┬═══════╝
                            │  ▼ writes messages/convs      │          │ XREADGROUP
                            └──┬────────────────────────────┘          ▼
                               │                           ┌──────────────────────┐
                               │                           │ Ingestion Consumer   │
                               │                           │ • 2nd PII pass       │
                               │                           │ • idempotent UPSERT  │
                               │                           │ • XACK on commit     │
                               │                           └──────────┬───────────┘
                               │                                      │
                               │             ╔════════════════════════▼═══════╗
                               └────────────►║          PostgreSQL             ║
                                             ║  conversations · messages ·     ║
                                             ║  inference_logs · log_events    ║
                                             ╚═════════════════════════════════╝
```

**Why six services and not one monolith?** Each piece can fail, scale, or be replaced in isolation. The chatbot can keep serving users while the consumer is restarted; the SDK can ship to a different ingestion target without touching the chatbot; ingestion scales horizontally without affecting chat latency.

**Boundary rules (enforced by deployment topology):**

| Producer | Consumer | Channel | Coupling |
|---|---|---|---|
| Frontend → Chatbot API | conversations + messages | HTTP/SSE | Sync, user-facing |
| Frontend → Ingestion API | stats | HTTP | Sync, dashboard |
| Chatbot SDK → Ingestion API | inference logs | HTTP (fire-and-forget) | **Async, never blocks chat** |
| Ingestion API → Consumer | log payloads | Redis Stream | **Async, durable, replayable** |
| Consumer → Postgres | inference_logs + log_events | TCP/SQL | Sync within worker |
| Chatbot API → Postgres | conversations + messages only | TCP/SQL | Sync within request |

The chatbot **never writes to `inference_logs`** and the consumer **never writes to `messages`** — this division of writers makes ownership obvious.

---

## 2. Ingestion Flow (end-to-end)

```
User clicks Send
    │
    ▼
[Frontend] POST /v1/conversations/{id}/messages   (Accept: text/event-stream)
    │
    ▼
[Chatbot API] 1. Persist user message → messages table
              2. Pull last N=10 turns from DB → build prompt history
              3. Register asyncio.Event in cancellation registry
              4. Instantiate SDK wrapper with provider/model overrides
              5. Begin SSE response
    │
    ▼
[SDK wrapper] t0 = perf_counter()
              try:
                async for chunk in provider.stream_chat(...):
                    if chunk.delta:
                        if first chunk: ttft_ms = perf_counter() - t0   ← TTFT captured
                        yield {"type":"token", "delta":...}              ← back to chatbot
                    if chunk.done:
                        capture prompt/completion/total tokens
                        break
              except Exception as exc:
                  status = "error", capture exc type + message
              finally:
                  ── ALWAYS executed ──
                  build LogPayload(request_id, provider, model, latency_ms,
                                    ttft_ms, tokens, status, input_preview,
                                    output_preview, started_at, completed_at)
                  redact(input_preview); redact(output_preview)
                  logger.emit(payload)   ← schedules async POST, does NOT await
                  yield {"type":"done", ...}
    │
    ▼ (each token, in real time)
[Chatbot API] forwards as `event: token\ndata: {"delta":...}\n\n`
[Frontend]    accumulates into the streaming assistant bubble (flushSync)
    │
    ▼ (when stream completes)
[Chatbot API] persists final assistant message → messages table
[Frontend]    fires getConversation(id) as belt-and-suspenders DB resync

                                Meanwhile, in parallel:

[SDK logger]   httpx.AsyncClient.post("/v1/logs", payload)   ← fire-and-forget
       │                                                      (errors swallowed,
       ▼                                                       warning to stderr)
[Ingestion API] POST /v1/logs
                  Pydantic validation (rejects malformed payloads at the door)
                  XADD inference_logs * data='{json}'         ← <5ms typical
                  return 202 Accepted
       │
       ▼ (decoupled — separate process)
[Consumer]   XREADGROUP inference_logs ingestion-workers worker-<pod>
             for each entry:
                 1. PII re-redact (defense in depth — SDK can lie)
                 2. INSERT … ON CONFLICT (request_id) DO UPDATE
                    (idempotent — same request_id = single row)
                 3. INSERT INTO log_events (audit trail, JSONB raw payload)
                 4. XACK only after both inserts commit
       │
       ▼
[Postgres]   inference_logs gains a row + log_events gains an audit row
       │
       ▼
[Dashboard]  /v1/stats/* queries hit inference_logs aggregates → charts update
```

**The critical guarantee:** if anything from the SDK rightward fails, **the chat user notices nothing.** Their tokens already streamed.

---

## 3. Component Responsibilities

### 3.1 Frontend ([`frontend/`](frontend/))

Stack: React 18 + Vite + TypeScript + React Router + Recharts.

| Responsibility | Implementation |
|---|---|
| Conversation sidebar (list, click-to-resume) | `App.tsx` — polls `/v1/conversations` every 5s |
| Multi-turn chat thread + composer | `pages/ChatPage.tsx` |
| SSE token streaming + render | `api.ts:streamChat()` + `flushSync` in `ChatPage` |
| Cancel mid-stream | Red **Stop** button → POST `/cancel` + `AbortController.abort()` |
| Model picker (new chat) | Modal in `App.tsx` |
| Model picker (inline, mid-chat) | Composer-bottom chip in `ChatPage.tsx` |
| Dashboard charts | `pages/DashboardPage.tsx` — 7 stat cards + 3 Recharts charts |
| Auto-resync after stream | `syncFromServer()` in `finally` block — fetches persisted message from DB |

### 3.2 Chatbot API ([`chatbot_api/`](chatbot_api/))

Stack: FastAPI + SQLAlchemy (async) + asyncpg + sse-starlette.

| Endpoint | Purpose |
|---|---|
| `POST /v1/conversations` | Create conversation with chosen provider/model |
| `GET /v1/conversations` | List recent 50 with `message_count` |
| `GET /v1/conversations/{id}` | Return conversation + full message history (for resume) |
| `POST /v1/conversations/{id}/cancel` | Sets `cancel_event`; marks conv `status='cancelled'` |
| `POST /v1/conversations/{id}/messages` | **SSE streaming chat** — see §2 |
| `GET /v1/conversations/models` | Catalog of providers + models for UI dropdowns |

**Owns:** conversation lifecycle, message persistence, context-window assembly (last `N=10` turns), in-memory cancellation registry.
**Does NOT own:** inference logging (SDK's job, off-the-hot-path).

### 3.3 SDK Wrapper ([`sdk/llm_sdk/`](sdk/llm_sdk/))

The "lightweight" requirement is enforced: zero framework deps, just `httpx` + `pydantic`. Provider SDKs (`openai`, `anthropic`, `google-generativeai`) are lazy-imported only when their provider is selected.

```
LLMClient
  ├── provider: openai | anthropic | gemini | mock   ← swappable
  ├── model: string
  ├── redact_pii: bool                                ← 1st PII pass
  └── logger: IngestionLogger                         ← fire-and-forget HTTP shipper

provider.stream_chat(model, messages, cancel_event) → AsyncIterator[StreamChunk]
  StreamChunk { delta, done, prompt_tokens, completion_tokens, total_tokens }
```

**Auto-fallback:** if `provider="openai"` but `OPENAI_API_KEY` is unset, the client silently swaps to `MockProvider`. Same for anthropic/gemini. This is how the system stays demoable with zero secrets.

**Metadata captured per call** (becomes a `LogPayload`):
```
request_id (UUID, idempotency key)   provider                model
conversation_id                       started_at (UTC)        completed_at (UTC)
status: success|error|cancelled       error_type             error_message
latency_ms                            ttft_ms                streamed (bool)
prompt_tokens, completion_tokens, total_tokens
input_preview (≤500 chars, redacted)  output_preview (≤500 chars, redacted)
metadata (JSONB, open-ended for future fields)
```

### 3.4 Ingestion API ([`ingestion_api/`](ingestion_api/))

Stateless, horizontally scalable.

| Endpoint | Purpose |
|---|---|
| `POST /v1/logs` | Validate → XADD to Redis Stream → 202 Accepted |
| `GET /v1/stats/overview` | Counts + avg + p95 latency + total tokens |
| `GET /v1/stats/latency` | p50/p95 over time (5-min or 1-hour buckets) |
| `GET /v1/stats/throughput` | Requests per minute (or hour) |
| `GET /v1/stats/errors` | Top-20 error types over the window |

### 3.5 Ingestion Consumer ([`ingestion_api/consumer.py`](ingestion_api/consumer.py))

```
loop:
    entries = XREADGROUP inference_logs ingestion-workers <consumer> count=32 block=2s
    for each entry:
        payload = LogPayload.model_validate(json)
        redact(input_preview); redact(output_preview)        # 2nd PII pass
        UPSERT inference_logs (ON CONFLICT request_id DO UPDATE)
        INSERT log_events (event_type, request_id, JSONB payload)
        XACK entry_id   ← only after BOTH inserts commit
```

If the consumer crashes mid-batch, un-ACKed entries are re-delivered. Idempotency on `request_id` makes redelivery safe.

---

## 4. Data Model

Four tables in [`db/init.sql`](db/init.sql). UUIDs everywhere, `TIMESTAMPTZ` (always UTC), `JSONB` for flexible metadata.

### 4.1 Why these four tables

| Table | Why it exists |
|---|---|
| `conversations` | Top-level chat session. Stores chosen provider/model + status (`active`/`cancelled`/`archived`) for soft-delete. |
| `messages` | One row per chat turn. **Separate from `inference_logs`** because: (a) errors produce logs without messages, (b) UI scrolls messages while dashboards group by model. |
| `inference_logs` | One row per LLM API call. **Analytics source of truth.** `request_id UNIQUE` for idempotency. |
| `log_events` | Append-only audit of every payload received. JSONB survives schema migrations. |

### 4.2 Key column choices

| Column | Type | Rationale |
|---|---|---|
| `id` | `UUID PRIMARY KEY DEFAULT gen_random_uuid()` | Sequence-free, multi-writer-safe |
| `*_at` | `TIMESTAMPTZ` | Always UTC at DB layer; timezone conversion is presentation-only |
| `metadata` | `JSONB` | Add fields without migrations: cost, tags, A/B IDs |
| `messages.content` + `messages.redacted_content` | both `TEXT` | Keep raw for dev (env-gated), always store redacted for safe display |
| `inference_logs.request_id` | `TEXT NOT NULL UNIQUE` | Idempotency key — `ON CONFLICT DO UPDATE` |
| `inference_logs.ttft_ms` | separate from `latency_ms` | Streaming-specific. Bad TTFT + good latency = throughput; good TTFT + bad latency = generation length. Different incidents. |
| `status` | `CHECK (...)` enum | Catches bad inserts at the DB boundary |

### 4.3 Indexes (tuned for actual queries)

| Index | Powers |
|---|---|
| `idx_conversations_updated_at (updated_at DESC)` | Sidebar "recent first" |
| `idx_messages_conv_created (conversation_id, created_at)` | Loading message thread |
| `idx_inf_conv_started (conversation_id, started_at DESC)` | "Logs for this conversation" |
| `idx_inf_model_started (model, started_at DESC)` | Per-model dashboard charts |
| `idx_inf_status_started (status, started_at DESC)` | Error-rate queries |
| `idx_inf_started (started_at DESC)` | Time-window scans |
| `idx_log_events_received` + `idx_log_events_req` | Replay debugging |

### 4.4 What we deliberately did NOT model

- **Users / tenants** — single-tenant demo. Would add `user_id` FK + RLS.
- **Cost in USD** — would compute via `(provider, model) → $/1k token` table, store on `metadata`.
- **Rate limits** — handled at provider level today.

---

## 5. Logging Strategy

| Concern | Decision | Reasoning |
|---|---|---|
| **Where captured** | SDK wrapper's `finally` block | Single chokepoint — no "we forgot to log" |
| **What captured** | Full LogPayload (§3.3) | Enough for cost, latency, error triage, replay |
| **Sync vs async** | Async via `asyncio.create_task` | Chat **never blocks on log writes** |
| **Idempotency** | Client-side UUID + `ON CONFLICT DO UPDATE` | Safe to retry |
| **Failure mode** | Swallow + warn to stderr | Logging breakage must not break product |
| **Sampling** | None (v1) | Demo scale. Production: env-driven sample rate by status. |
| **Preview bounds** | 500 chars each | Prevents runaway storage |
| **PII** | Redact in SDK (1st) AND in consumer (2nd) | Defense in depth: SDK can lie |
| **Audit** | Every payload also in `log_events` JSONB | Replay or schema-evolve without losing data |
| **Correlation** | `request_id` ties SDK ↔ ingestion ↔ consumer ↔ DB | Distributed-trace-friendly without OpenTelemetry |

---

## 6. PII Redaction

Implemented at two layers (defense in depth).

| Pattern | Approach | Replacement |
|---|---|---|
| Email | Standard regex | `[REDACTED-EMAIL]` |
| Phone | NANP-style with explicit separators (avoids false positives on bare digits) | `[REDACTED-PHONE]` |
| SSN | `\d{3}-\d{2}-\d{4}` | `[REDACTED-SSN]` |
| Credit card | 13–19 digits + **Luhn check** to suppress false positives | `[REDACTED-CC]` |

**Why regex (not Presidio / NER):**
- Zero added deps — fits the "lightweight" SDK constraint
- Deterministic + auditable
- Catches >90% high-frequency cases

**Known limitations** (documented for production hardening):
- Won't catch names mid-sentence (NER would)
- Won't catch domain-specific IDs (passport, customer IDs)
- Migration to Microsoft Presidio = single-file swap

---

## 7. Scaling Considerations

What breaks first as we ramp:

```
       throughput (req/min)
       ─────────────────────────────────────────────────►
   1   ▲ #1 chatbot-api process saturates (CPU + SSE connections)
       │
       │  Fix: horizontal scale chatbot-api. Move cancellation registry
       │  from in-memory → Redis pub/sub keyed on conversation_id.
       │  Drop the replicas=1 pin in k8s.
       │
  10  ─┼─ #2 inference_logs insert lag visible in dashboard
       │
       │  Fix: scale ingestion-consumer replicas. Each pod becomes a
       │  consumer-group member; Redis auto-partitions pending entries.
       │
  100 ─┼─ #3 ingestion-api CPU (validation + XADD volume)
       │
       │  Fix: scale ingestion-api (already 2 replicas in k8s).
       │
 1000 ─┼─ #4 Postgres write IOPS on inference_logs
       │
       │  Fix: partition inference_logs by month on started_at.
       │  Read replica for dashboard queries (lower freshness OK).
       │
10000 ─┼─ #5 dashboard latency on multi-million-row scans
       │
       │  Fix: hot/cold tier. Last 7d in Postgres, archive older to
       │  ClickHouse or S3+Athena. Pre-compute hourly rollups.
       │
100k+  ▼ #6 Redis Stream memory growth
       │
       │  Fix: XADD with MAXLEN ~ 100000 to cap. Once persisted to
       │  Postgres we don't need it in Redis.
       ▼
```

The scaling story is **"add more workers / partitions" not "rewrite the system."**

---

## 8. Failure Handling

| Failure | Behavior | User impact | Recovery |
|---|---|---|---|
| **Ingestion API down** | SDK `emit()` swallows + logs warning | None — chat works | Logs for that period **lost** (v1). v2: disk buffer + retry. |
| **Consumer down** | API still accepts logs; queue in Redis | None | Worker resumes, drains from consumer-group offset |
| **Postgres down** | Consumer can't commit, no XACK → re-delivered | High — chat unusable | Idempotency makes redelivery safe; chat resumes when DB back |
| **Redis down** | Ingestion `/logs` returns 503; SDK swallows | None for chat | Same as ingestion-down |
| **Provider 5xx / timeout** | SDK catches, yields `error` event, logs `status=error` with type+message | Visible — that message failed | User retries by sending again |
| **User clicks Stop mid-stream** | `cancel_event.set()` observed by provider loop; stream closes; log written with `status='cancelled'` + partial output | Intentional | — |
| **Duplicate log** | `ON CONFLICT DO UPDATE` — second insert updates row to latest snapshot | None | — |
| **Long conversation exceeds context** | SDK sends only last `CONTEXT_WINDOW_TURNS` (default 10). Older stays in DB visible in UI but not sent. | Possible loss of long-range memory | v2: summarize trimmed turns into a system message |
| **No API key** | SDK auto-falls back to `MockProvider` | Chat works end-to-end; logs flow | — |
| **Frontend stale JS** | UI may not match latest backend | Visible | Hard refresh (`Cmd+Shift+R`). v2: cache busting in script tag. |

---

## 9. Trade-offs and Why

| Decision | Alternative considered | Why this won |
|---|---|---|
| **Postgres** for messages + logs | Postgres + ClickHouse | One process to operate at demo scale; JSONB covers flexible-metadata. Migration to ClickHouse is a write-path-only change at >10k req/min. |
| **Redis Streams** as event bus | Kafka / RabbitMQ / NATS | Already needed Redis; consumer-group semantics + at-least-once delivery; one fewer container. |
| **Fire-and-forget logger** (no buffer) | Local disk buffer + retry | "Lightweight" was explicit. Spec'd as v2; data we'd recover (seconds of logs) isn't worth ops cost at this scale. |
| **Regex PII redaction** | Microsoft Presidio + NER | Zero added deps. Production: documented swap path (one module). |
| **In-memory cancellation registry** | Redis pub/sub | Single chatbot-api replica is enough for demo; easier to reason about. Swap is well-understood. |
| **Raw SQL via SQLAlchemy core** | Full ORM | Schema is small (4 tables); explicit queries; nothing magical. Easier to review. |
| **Sliding window** for context | Token-budget / summarization | Predictable cost. Easy to tune via env. Documented improvement path. |
| **Vite dev server in container** | `vite build` + nginx | Faster demo iteration. For prod, switch to multi-stage Dockerfile. |
| **Per-conversation pinned model, with per-message override** | Lock per-thread vs only-global default | Best of both: defaults from env, override at creation, override at message level. Each `inference_logs` row records the actual model used. |

---

## 10. What I'd Improve With More Time

Concrete, prioritized:

1. **SDK durability** — local disk buffer + exponential-backoff retry when ingestion is unreachable
2. **Tracing** — OpenTelemetry context propagation frontend → chatbot → ingestion → consumer
3. **Cost tracking** — `(provider, model) → $/1k token` table; USD on dashboard
4. **Real test suite** — pytest for SDK + ingestion (especially idempotency + PII edge cases), Playwright for UI cancel flow
5. **PII upgrade** — swap regex for Presidio + small NER model
6. **Multi-replica chatbot** — Redis pub/sub for cancellation
7. **Conversation summarization** — when sliding window cuts in, summarize dropped turns
8. **Read replica** for dashboard queries
9. **Auth + multi-tenancy** — `user_id` FK + RLS; JWT-based auth
10. **Real production frontend build** — multi-stage Dockerfile, nginx, asset hashing

---

## 11. File Map

```
.
├── chatbot_api/
│   ├── main.py                    # FastAPI app
│   ├── config.py                  # env-driven settings
│   ├── db.py                      # SQLAlchemy async engine
│   ├── repository.py              # raw SQL operations
│   ├── cancellation.py            # in-memory asyncio.Event registry
│   └── routers/
│       ├── chat.py                # SSE streaming endpoint
│       └── conversations.py       # CRUD + cancel + models catalog
│
├── ingestion_api/
│   ├── main.py                    # FastAPI app
│   ├── consumer.py                # Redis Streams worker → Postgres
│   ├── schemas.py                 # Pydantic wire schemas
│   ├── pii.py                     # 2nd-pass PII redaction
│   └── routers/
│       ├── logs.py                # POST /v1/logs (validates → XADD)
│       └── stats.py               # GET /v1/stats/* (dashboard queries)
│
├── sdk/llm_sdk/                   # The wrapper itself
│   ├── client.py                  # LLMClient — main entrypoint
│   ├── logger.py                  # IngestionLogger — fire-and-forget HTTP
│   ├── pii.py                     # 1st-pass redaction
│   ├── models.py                  # LogPayload Pydantic schema
│   └── providers/
│       ├── base.py                # Provider ABC + StreamChunk dataclass
│       ├── openai_provider.py
│       ├── anthropic_provider.py
│       ├── gemini_provider.py
│       └── mock_provider.py       # always-on fallback when no key
│
├── frontend/src/
│   ├── App.tsx                    # routes, sidebar, new-chat modal
│   ├── api.ts                     # all HTTP/SSE clients
│   ├── pages/
│   │   ├── ChatPage.tsx           # message thread, composer, model chip
│   │   └── DashboardPage.tsx      # cards + 3 Recharts charts
│   └── styles.css
│
├── db/init.sql                    # schema (auto-applied on first Postgres boot)
├── docker-compose.yml             # 6 services, healthchecks, volumes, hot-reload
├── k8s/base/                      # 18 Kubernetes manifests
└── k8s/deploy.sh                  # one-command kind/minikube/k3s deployer
```

---

**For setup instructions and the bonus-feature checklist, see [README.md](./README.md).**
