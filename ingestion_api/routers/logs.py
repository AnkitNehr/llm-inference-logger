"""POST /v1/logs

Validates the payload then pushes it onto a Redis Stream. The DB write
happens asynchronously in `ingestion_api/consumer.py`. We return 202 fast
so the SDK is never blocked by DB or downstream backpressure.
"""
from __future__ import annotations
import json
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Request, status

from ..config import settings
from ..schemas import LogPayload

router = APIRouter(prefix="/v1/logs", tags=["logs"])
log = logging.getLogger("ingestion.logs")


def _redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def ingest(payload: LogPayload, request: Request) -> dict:
    try:
        body = payload.model_dump(mode="json")
        await _redis(request).xadd(settings.log_stream, {"data": json.dumps(body)})
        return {"accepted": True, "request_id": payload.request_id}
    except Exception as exc:  # noqa: BLE001
        log.exception("failed to enqueue log")
        raise HTTPException(status_code=503, detail=f"queue unavailable: {exc}")
