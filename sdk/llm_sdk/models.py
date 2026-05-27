from __future__ import annotations
from datetime import datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LogPayload(BaseModel):
    """Wire format the SDK sends to the ingestion API."""
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
