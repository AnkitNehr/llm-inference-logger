"""GET /v1/stats/* — analytics endpoints powering the dashboard.

All queries hit inference_logs. Window defaults to last 24h; pass
?window_minutes= to override.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session

router = APIRouter(prefix="/v1/stats", tags=["stats"])


def _since(window_minutes: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=window_minutes)


@router.get("/overview")
async def overview(
    window_minutes: int = Query(1440, ge=1, le=10080),
    session: AsyncSession = Depends(get_session),
) -> dict:
    since = _since(window_minutes)
    result = await session.execute(
        text(
            """
            SELECT
                COUNT(*) AS total_requests,
                COUNT(*) FILTER (WHERE status='success') AS success_count,
                COUNT(*) FILTER (WHERE status='error') AS error_count,
                COUNT(*) FILTER (WHERE status='cancelled') AS cancelled_count,
                COALESCE(AVG(latency_ms),0) AS avg_latency_ms,
                COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms),0) AS p95_latency_ms,
                COALESCE(SUM(total_tokens),0) AS total_tokens
            FROM inference_logs
            WHERE started_at >= :since
            """
        ),
        {"since": since},
    )
    row = result.mappings().one()
    return {k: (float(v) if k in ("avg_latency_ms", "p95_latency_ms") else int(v)) for k, v in row.items()}


@router.get("/latency")
async def latency(
    window_minutes: int = Query(1440, ge=1, le=10080),
    session: AsyncSession = Depends(get_session),
) -> dict:
    since = _since(window_minutes)
    bucket = "5 minutes" if window_minutes <= 360 else "1 hour"
    result = await session.execute(
        text(
            f"""
            SELECT
                date_trunc('minute', started_at) - (EXTRACT(MINUTE FROM started_at)::int %% 5) * interval '1 minute' AS bucket,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY latency_ms) AS p50,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95
            FROM inference_logs
            WHERE started_at >= :since AND latency_ms IS NOT NULL
            GROUP BY bucket
            ORDER BY bucket
            """
        ) if window_minutes <= 360 else text(
            """
            SELECT
                date_trunc('hour', started_at) AS bucket,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY latency_ms) AS p50,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95
            FROM inference_logs
            WHERE started_at >= :since AND latency_ms IS NOT NULL
            GROUP BY bucket
            ORDER BY bucket
            """
        ),
        {"since": since},
    )
    points = [
        {"bucket": r["bucket"].isoformat(), "p50": float(r["p50"]), "p95": float(r["p95"])}
        for r in result.mappings()
    ]
    return {"bucket_size": bucket, "points": points}


@router.get("/throughput")
async def throughput(
    window_minutes: int = Query(1440, ge=1, le=10080),
    session: AsyncSession = Depends(get_session),
) -> dict:
    since = _since(window_minutes)
    grain = "minute" if window_minutes <= 120 else "hour"
    result = await session.execute(
        text(
            f"""
            SELECT date_trunc('{grain}', started_at) AS bucket, COUNT(*) AS requests
            FROM inference_logs
            WHERE started_at >= :since
            GROUP BY bucket
            ORDER BY bucket
            """
        ),
        {"since": since},
    )
    return {
        "bucket_size": grain,
        "points": [
            {"bucket": r["bucket"].isoformat(), "requests": int(r["requests"])}
            for r in result.mappings()
        ],
    }


@router.get("/errors")
async def errors(
    window_minutes: int = Query(1440, ge=1, le=10080),
    session: AsyncSession = Depends(get_session),
) -> dict:
    since = _since(window_minutes)
    result = await session.execute(
        text(
            """
            SELECT COALESCE(error_type,'unknown') AS error_type, COUNT(*) AS count
            FROM inference_logs
            WHERE started_at >= :since AND status='error'
            GROUP BY error_type
            ORDER BY count DESC
            LIMIT 20
            """
        ),
        {"since": since},
    )
    return {"breakdown": [dict(r) for r in result.mappings()]}
