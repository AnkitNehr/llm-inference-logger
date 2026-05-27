"""Redis Streams consumer worker.

Reads `inference_logs` stream via a consumer group, persists each event
to Postgres (idempotent on request_id), and also writes an audit row
to log_events. Runs as a separate compose service so it can scale
independently of the HTTP ingestion API.
"""
from __future__ import annotations
import asyncio
import json
import logging
import signal
import sys

import redis.asyncio as aioredis
from redis.exceptions import ResponseError
from sqlalchemy import text

from .config import settings
from .db import SessionLocal
from .pii import redact
from .schemas import LogPayload

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ingestion.consumer")


UPSERT_LOG = text(
    """
    INSERT INTO inference_logs (
        request_id, conversation_id, provider, model, status,
        error_type, error_message, latency_ms, ttft_ms,
        prompt_tokens, completion_tokens, total_tokens,
        input_preview, output_preview, streamed,
        started_at, completed_at, metadata
    ) VALUES (
        :request_id,
        CAST(NULLIF(:conversation_id,'') AS UUID),
        :provider, :model, :status,
        :error_type, :error_message, :latency_ms, :ttft_ms,
        :prompt_tokens, :completion_tokens, :total_tokens,
        :input_preview, :output_preview, :streamed,
        :started_at, :completed_at, CAST(:metadata AS JSONB)
    )
    ON CONFLICT (request_id) DO UPDATE SET
        status            = EXCLUDED.status,
        error_type        = EXCLUDED.error_type,
        error_message     = EXCLUDED.error_message,
        latency_ms        = EXCLUDED.latency_ms,
        ttft_ms           = EXCLUDED.ttft_ms,
        prompt_tokens     = EXCLUDED.prompt_tokens,
        completion_tokens = EXCLUDED.completion_tokens,
        total_tokens      = EXCLUDED.total_tokens,
        input_preview     = EXCLUDED.input_preview,
        output_preview    = EXCLUDED.output_preview,
        completed_at      = EXCLUDED.completed_at,
        metadata          = EXCLUDED.metadata;
    """
)

INSERT_EVENT = text(
    """
    INSERT INTO log_events (event_type, request_id, payload)
    VALUES ('inference_log', :request_id, CAST(:payload AS JSONB))
    """
)


async def ensure_group(r: aioredis.Redis) -> None:
    try:
        await r.xgroup_create(settings.log_stream, settings.consumer_group, id="$", mkstream=True)
        log.info("created consumer group %s on %s", settings.consumer_group, settings.log_stream)
    except ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            return
        raise


async def handle(payload_json: str) -> None:
    raw = json.loads(payload_json)
    payload = LogPayload.model_validate(raw)

    if settings.pii_redact:
        payload.input_preview = redact(payload.input_preview)
        payload.output_preview = redact(payload.output_preview)

    params = {
        "request_id": payload.request_id,
        "conversation_id": payload.conversation_id or "",
        "provider": payload.provider,
        "model": payload.model,
        "status": payload.status,
        "error_type": payload.error_type,
        "error_message": payload.error_message,
        "latency_ms": payload.latency_ms,
        "ttft_ms": payload.ttft_ms,
        "prompt_tokens": payload.prompt_tokens,
        "completion_tokens": payload.completion_tokens,
        "total_tokens": payload.total_tokens,
        "input_preview": payload.input_preview,
        "output_preview": payload.output_preview,
        "streamed": payload.streamed,
        "started_at": payload.started_at,
        "completed_at": payload.completed_at,
        "metadata": json.dumps(payload.metadata or {}),
    }
    async with SessionLocal() as session:
        async with session.begin():
            await session.execute(UPSERT_LOG, params)
            await session.execute(
                INSERT_EVENT,
                {"request_id": payload.request_id, "payload": json.dumps(payload.model_dump(mode="json"))},
            )


async def run() -> None:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    await ensure_group(r)
    log.info("consumer started: stream=%s group=%s name=%s",
             settings.log_stream, settings.consumer_group, settings.consumer_name)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    while not stop.is_set():
        try:
            resp = await r.xreadgroup(
                groupname=settings.consumer_group,
                consumername=settings.consumer_name,
                streams={settings.log_stream: ">"},
                count=32,
                block=2000,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("xreadgroup failed: %s", exc)
            await asyncio.sleep(1)
            continue

        if not resp:
            continue
        for _stream, entries in resp:
            for entry_id, fields in entries:
                try:
                    await handle(fields.get("data", "{}"))
                    await r.xack(settings.log_stream, settings.consumer_group, entry_id)
                except Exception as exc:  # noqa: BLE001
                    log.exception("handler failed for %s: %s", entry_id, exc)

    await r.aclose()
    log.info("consumer stopped")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(0)
