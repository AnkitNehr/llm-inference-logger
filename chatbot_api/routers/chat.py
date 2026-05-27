"""POST /v1/conversations/{conv_id}/messages — SSE streaming chat.

Pulls last-N-turn context, calls the SDK-wrapped provider, streams tokens
back to the client via Server-Sent Events, and persists the assistant
message at the end.
"""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

# Make the shared SDK importable inside the container
sys.path.insert(0, str(Path("/app")))
from llm_sdk import LLMClient, ChatMessage  # noqa: E402
from llm_sdk.pii import redact as pii_redact  # noqa: E402

from .. import repository as repo
from ..cancellation import register, release
from ..config import settings
from ..db import get_session, SessionLocal

router = APIRouter(prefix="/v1/conversations", tags=["chat"])


class SendMessage(BaseModel):
    content: str
    provider: Optional[str] = None
    model: Optional[str] = None


def _to_chat_messages(rows: list[dict], system_prompt: Optional[str], window: int) -> list[ChatMessage]:
    msgs: list[ChatMessage] = []
    if system_prompt:
        msgs.append(ChatMessage(role="system", content=system_prompt))
    # Keep the last `window` * 2 messages (user+assistant pairs)
    trimmed = rows[-(window * 2):]
    for r in trimmed:
        if r["role"] in ("user", "assistant"):
            msgs.append(ChatMessage(role=r["role"], content=r["content"]))
    return msgs


@router.post("/{conv_id}/messages")
async def send_message(
    conv_id: UUID,
    payload: SendMessage,
    session: AsyncSession = Depends(get_session),
):
    conv = await repo.get_conversation(session, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="conversation not found")

    # Reset cancelled status when a user sends a new message
    if conv["status"] == "cancelled":
        await repo.update_status(session, conv_id, "active")

    # Persist the user message
    redacted_user = pii_redact(payload.content) if settings.pii_redact else payload.content
    await repo.insert_message(
        session, conv_id, role="user",
        content=payload.content if settings.store_raw_content else redacted_user,
        redacted_content=redacted_user,
    )

    history = await repo.get_messages(session, conv_id)
    messages = _to_chat_messages(history, conv.get("system_prompt"), settings.context_window_turns)

    # Per-message override takes precedence over the conversation's stored choice.
    # If overridden, also persist it so the sidebar reflects the latest model used.
    chosen_provider = payload.provider or conv.get("provider") or settings.default_provider
    chosen_model = payload.model or conv.get("model") or settings.default_model
    if (payload.provider and payload.provider != conv.get("provider")) or \
       (payload.model and payload.model != conv.get("model")):
        await repo.update_provider_model(session, conv_id, chosen_provider, chosen_model)

    client = LLMClient(
        provider=chosen_provider,
        model=chosen_model,
        ingestion_url=settings.ingestion_url,
        redact_pii=settings.pii_redact,
    )
    cancel_event = register(str(conv_id))

    async def event_stream():
        request_id: Optional[str] = None
        full_output = ""
        status = "success"
        try:
            async for chunk in client.stream_chat(
                messages,
                conversation_id=str(conv_id),
                cancel_event=cancel_event,
            ):
                if chunk["type"] == "token":
                    full_output += chunk["delta"]
                    yield {"event": "token", "data": json.dumps({"delta": chunk["delta"]})}
                elif chunk["type"] == "error":
                    status = "error"
                    yield {"event": "error", "data": json.dumps({"message": chunk["message"]})}
                elif chunk["type"] == "done":
                    request_id = chunk["request_id"]
                    status = chunk["status"]
                    yield {
                        "event": "done",
                        "data": json.dumps({
                            "request_id": request_id,
                            "status": status,
                            "usage": chunk.get("usage", {}),
                        }),
                    }
        finally:
            release(str(conv_id))
            await client.aclose()
            # Persist assistant message in a fresh session — request session
            # is closed once the generator yields control back to starlette.
            if full_output:
                async with SessionLocal() as s:
                    await repo.insert_message(
                        s, conv_id, role="assistant",
                        content=full_output if settings.store_raw_content else (
                            pii_redact(full_output) if settings.pii_redact else full_output
                        ),
                        redacted_content=pii_redact(full_output) if settings.pii_redact else full_output,
                        inference_log_id=None,  # log row written async by ingestion
                    )

    return EventSourceResponse(event_stream())
