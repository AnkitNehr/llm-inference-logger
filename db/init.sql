-- LLM Inference Logger schema
-- Conventions: UUID PKs, TIMESTAMPTZ everywhere, JSONB for flexible metadata,
-- soft-delete via status fields (never hard-delete an inference log — audit value).

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =====================================================================
-- conversations: top-level chat session
-- =====================================================================
CREATE TABLE IF NOT EXISTS conversations (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title        TEXT NOT NULL DEFAULT 'New conversation',
    status       TEXT NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active','cancelled','archived')),
    provider     TEXT,
    model        TEXT,
    system_prompt TEXT,
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
    ON conversations (updated_at DESC);

-- =====================================================================
-- messages: one row per chat turn (user / assistant / system)
-- redacted_content stores the PII-scrubbed version used for analytics/display
-- =====================================================================
CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    content         TEXT NOT NULL,
    redacted_content TEXT,
    token_count     INTEGER,
    inference_log_id UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_conv_created
    ON messages (conversation_id, created_at);

-- =====================================================================
-- inference_logs: one row per LLM API call.
-- request_id is the SDK-generated idempotency key.
-- =====================================================================
CREATE TABLE IF NOT EXISTS inference_logs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id          TEXT NOT NULL UNIQUE,
    conversation_id     UUID REFERENCES conversations(id) ON DELETE SET NULL,
    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,
    status              TEXT NOT NULL
                        CHECK (status IN ('success','error','cancelled','in_progress')),
    error_type          TEXT,
    error_message       TEXT,
    latency_ms          INTEGER,
    ttft_ms             INTEGER,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    total_tokens        INTEGER,
    input_preview       TEXT,
    output_preview      TEXT,
    streamed            BOOLEAN NOT NULL DEFAULT false,
    started_at          TIMESTAMPTZ NOT NULL,
    completed_at        TIMESTAMPTZ,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_inf_conv_started   ON inference_logs (conversation_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_inf_model_started  ON inference_logs (model, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_inf_status_started ON inference_logs (status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_inf_started        ON inference_logs (started_at DESC);

-- =====================================================================
-- log_events: append-only audit of every payload received by ingestion.
-- Decouples raw-ingest from the normalized inference_logs table so we can
-- replay or debug payload-level issues without losing data.
-- =====================================================================
CREATE TABLE IF NOT EXISTS log_events (
    id           BIGSERIAL PRIMARY KEY,
    event_type   TEXT NOT NULL,
    request_id   TEXT,
    payload      JSONB NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_log_events_received ON log_events (received_at DESC);
CREATE INDEX IF NOT EXISTS idx_log_events_req      ON log_events (request_id);
