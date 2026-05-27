"""Pydantic schemas for the ingestion API wire format.
Mirrors sdk/llm_sdk/models.LogPayload but lives in this service so the
ingestion API has no runtime dependency on the SDK package.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class LogPayload(BaseModel):
    request_id: str
    conversation_id: Optional[str] = None
    provider: str
    model: str
    status: Literal["success", "error", "cancelled", "in_progress"]
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms: Optional[int] = None
    ttft_ms: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    input_preview: Optional[str] = None
    output_preview: Optional[str] = None
    streamed: bool = False
    started_at: datetime
    completed_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OverviewStats(BaseModel):
    total_requests: int
    success_count: int
    error_count: int
    cancelled_count: int
    avg_latency_ms: float
    p95_latency_ms: float
    total_tokens: int


class TimeBucket(BaseModel):
    bucket: datetime
    value: float


class LatencyBuckets(BaseModel):
    p50: list[TimeBucket]
    p95: list[TimeBucket]


class ThroughputBucket(BaseModel):
    bucket: datetime
    requests: int


class ErrorBreakdownRow(BaseModel):
    error_type: str
    count: int
