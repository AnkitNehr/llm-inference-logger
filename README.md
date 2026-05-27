# Ollive — LLM Inference Logging & Ingestion System

A lightweight, end-to-end LLM observability stack: a streaming chatbot, an SDK wrapper that captures inference metadata, an event-driven ingestion pipeline, a Postgres datastore, and a real-time dashboard. Runs with a single `docker compose up`.

## What's in here

| Component | Path | Port |
|---|---|---|
| Frontend (React + Vite) | `frontend/` | 5173 |
| Chatbot API (FastAPI, SSE) | `chatbot_api/` | 8001 |
| Ingestion API (FastAPI) | `ingestion_api/` | 8002 |
| Ingestion Consumer (Redis Streams worker) | `ingestion_api/consumer.py` | — |
| SDK / wrapper | `sdk/llm_sdk/` | — |
| Database schema | `db/init.sql` | — |
| Postgres | docker | 5432 |
| Redis (event bus) | docker | 6379 |
| Kubernetes manifests | [`k8s/`](k8s/) | — |

## Setup — one command

```bash
cp .env.example .env
# (optional) edit .env and set OPENAI_API_KEY=sk-... — without a key the mock provider runs.
docker compose up --build
```

Then open:
- Chat UI → http://localhost:5173
- Chatbot API docs → http://localhost:8001/docs
- Ingestion API docs → http://localhost:8002/docs

Tear down (and wipe DB):
```bash
docker compose down -v
```

### Kubernetes (self-hosted: kind / minikube / k3s)

```bash
./k8s/deploy.sh           # build images, load into cluster, kubectl apply -k
# UI:        http://localhost:30173
# Chatbot:   http://localhost:30001
# Ingestion: http://localhost:30002
./k8s/deploy.sh --teardown   # wipe
```

Manifests, scaling notes, and Secret-setting recipes are in [`k8s/README.md`](k8s/README.md).

## Architecture (overview)

```
┌────────────┐    SSE    ┌─────────────┐   async POST   ┌──────────────┐
│  Frontend  ├──────────►│ Chatbot API ├───────────────►│ Ingestion API │
│  (React)   │◄──────────┤  + SDK      │   /v1/logs     │  (validate)  │
└─────┬──────┘  stream   └──────┬──────┘                 └──────┬───────┘
      │ stats                   │ writes msgs                   │ XADD
      ▼                         ▼                               ▼
┌─────────────┐          ┌───────────────┐               ┌──────────────┐
│ Dashboard   │          │  Postgres     │◄──────────────┤ Redis Stream │
│ (Recharts)  │◄─────────┤  conversations│   consumer    │ inference_logs│
└─────────────┘          │  messages     │   worker      └──────────────┘
                         │  inference_logs                       
                         │  log_events                           
                         └───────────────┘
```

Full detail in [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Schema design decisions

Four tables in `db/init.sql`:

| Table | Why it exists | Key choices |
|---|---|---|
| `conversations` | Top-level chat session. | UUID PK; `status` enum (`active`/`cancelled`/`archived`) for soft-delete; `JSONB metadata` for forward-compat. |
| `messages` | One row per chat turn. | `role` CHECK constraint; `content` + `redacted_content` (we keep raw for dev, redacted for safe display); FK to `conversations` with `ON DELETE CASCADE`. |
| `inference_logs` | One row per LLM API call. **Separate** from messages because: (1) errors produce logs but no message, (2) different access pattern — UI reads messages, dashboards read logs. | `request_id UNIQUE` for **idempotency** (same payload received twice doesn't double-write); `started_at`/`completed_at` distinct from `created_at` (ingestion can be delayed); `ttft_ms` separate from `latency_ms` for streaming analytics; indexes tuned for the dashboard queries. |
| `log_events` | Append-only raw payload audit. | BIGSERIAL — high write volume; `payload JSONB` lets us replay or debug payload-level issues without losing data even if `inference_logs` schema evolves. |

**Indexes** are chosen for the actual dashboard queries — composite `(model, started_at DESC)` for per-model time-series, `(status, started_at DESC)` for error rate over time, etc.

## Tradeoffs made

| Choice | Why | What I gave up |
|---|---|---|
| **Postgres** (not Kafka + ClickHouse) | One process to operate; JSONB covers flexible-metadata needs; trivial dev setup. | At >10k req/min sustained, would migrate analytics to ClickHouse. |
| **Redis Streams** (not Kafka/RabbitMQ) | Already needed Redis; consumer-group semantics + at-least-once delivery; one fewer container. | No tiered storage, no replay-from-arbitrary-offset across days. |
| **Fire-and-forget logger** (no buffer/retry) | "Lightweight" was an explicit requirement; chat must never be blocked by ingestion. | If ingestion is hard-down, those logs are lost. Spec: would add a local disk buffer with retry. |
| **Regex PII redaction** (not Presidio) | Zero extra dependencies, fast, deterministic; catches the common cases (email, phone, SSN, Luhn-valid CC). | Lower recall than NER — wouldn't catch a name typed mid-sentence. |
| **In-memory cancellation registry** | Single-process is enough for a demo; trivial to test. | Doesn't survive a chatbot-api restart and doesn't scale across replicas. Would move to Redis pub/sub. |
| **Raw SQL via SQLAlchemy core** (not full ORM) | Schema is small; queries are explicit; less magic for reviewers. | Manual mapping. Acceptable for this size. |
| **Short context window = last N turns** (no summarization) | Simple, predictable token cost; easy to tune via env. | Loses long-conversation memory. Spec: would add summarization once N is hit. |
| **No auth, no tests beyond smoke** | Time budget. | Production-ready hardening missing. |

## What I'd improve with more time

- **SDK durability:** local disk buffer + exponential-backoff retry when ingestion is unreachable.
- **Real test suite:** pytest for SDK + ingestion handlers, Playwright for the UI cancel flow.
- **k8s manifests:** Deployment + Service + ConfigMap + Secret + HPA per service; PostgreSQL via Bitnami chart.
- **Multi-replica cancellation:** Redis pub/sub channel keyed by `conversation_id`.
- **Cost tracking:** map `(provider, model)` → $/1k tokens and surface USD on the dashboard.
- **Tracing:** OpenTelemetry context propagation from frontend → chatbot → ingestion → consumer for end-to-end traces.
- **Conversation summarization** when sliding-window cuts in.
- **PII upgrade:** swap regex for Microsoft Presidio + a small NER model.
- **Read-replicas / partitioning** on `inference_logs` (by `started_at` month) when retention grows past 90 days.

## Demo

Screenshots and a short Loom walkthrough are in the submission packet (sent separately). The system is fully runnable locally via `docker compose up --build`.
