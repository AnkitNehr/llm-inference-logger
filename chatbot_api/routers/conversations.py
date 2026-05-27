from __future__ import annotations
import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import repository as repo
from ..cancellation import cancel as cancel_stream
from ..config import settings
from ..db import get_session

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])

# Curated model catalog. Marked "available" iff the provider's API key is set
# (mock is always available). The UI uses this to gate dropdown choices.
_PROVIDER_MODELS = {
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
    "anthropic": [
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
    ],
    "gemini": [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-flash-latest",
    ],
    "mock": ["mock-model"],
}


def _provider_available(name: str) -> bool:
    return {
        "openai": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY", "").strip()),
        "gemini": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "mock": True,
    }.get(name, False)


class CreateConversation(BaseModel):
    title: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None


@router.get("/models", tags=["models"])
async def list_models() -> dict:
    """Return the catalog of providers + models the chatbot can use,
    with availability based on env-var-supplied keys."""
    return {
        "default_provider": settings.default_provider,
        "default_model": settings.default_model,
        "providers": [
            {
                "name": p,
                "available": _provider_available(p),
                "models": models,
            }
            for p, models in _PROVIDER_MODELS.items()
        ],
    }


@router.post("")
async def create(payload: CreateConversation, session: AsyncSession = Depends(get_session)):
    return await repo.create_conversation(
        session,
        title=payload.title or "New conversation",
        provider=payload.provider or settings.default_provider,
        model=payload.model or settings.default_model,
        system_prompt=payload.system_prompt or settings.default_system_prompt,
    )


@router.get("")
async def list_all(session: AsyncSession = Depends(get_session)):
    return await repo.list_conversations(session)


@router.get("/{conv_id}")
async def get_one(conv_id: UUID, session: AsyncSession = Depends(get_session)):
    conv = await repo.get_conversation(session, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="conversation not found")
    conv["messages"] = await repo.get_messages(session, conv_id)
    return conv


@router.post("/{conv_id}/cancel")
async def cancel(conv_id: UUID, session: AsyncSession = Depends(get_session)):
    conv = await repo.get_conversation(session, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="conversation not found")
    cancelled = cancel_stream(str(conv_id))
    await repo.update_status(session, conv_id, "cancelled")
    return {"cancelled_stream": cancelled, "status": "cancelled"}
