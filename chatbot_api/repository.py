"""Database operations for the chatbot service.
Raw SQL via SQLAlchemy core — keeps the dependency surface small.
"""
from __future__ import annotations
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def create_conversation(
    session: AsyncSession,
    title: str,
    provider: str,
    model: str,
    system_prompt: Optional[str],
) -> dict:
    row = (await session.execute(
        text(
            """
            INSERT INTO conversations (title, provider, model, system_prompt)
            VALUES (:title, :provider, :model, :system_prompt)
            RETURNING id, title, status, provider, model, system_prompt, created_at, updated_at
            """
        ),
        {"title": title, "provider": provider, "model": model, "system_prompt": system_prompt},
    )).mappings().one()
    await session.commit()
    return dict(row)


async def list_conversations(session: AsyncSession, limit: int = 50) -> list[dict]:
    result = await session.execute(
        text(
            """
            SELECT c.id, c.title, c.status, c.provider, c.model,
                   c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
            FROM conversations c
            ORDER BY c.updated_at DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return [dict(r) for r in result.mappings()]


async def get_conversation(session: AsyncSession, conv_id: UUID) -> Optional[dict]:
    row = (await session.execute(
        text("SELECT * FROM conversations WHERE id = :id"),
        {"id": conv_id},
    )).mappings().first()
    return dict(row) if row else None


async def get_messages(session: AsyncSession, conv_id: UUID) -> list[dict]:
    result = await session.execute(
        text(
            """
            SELECT id, role, content, redacted_content, token_count, inference_log_id, created_at
            FROM messages
            WHERE conversation_id = :id
            ORDER BY created_at ASC
            """
        ),
        {"id": conv_id},
    )
    return [dict(r) for r in result.mappings()]


async def insert_message(
    session: AsyncSession,
    conv_id: UUID,
    role: str,
    content: str,
    redacted_content: Optional[str],
    inference_log_id: Optional[str] = None,
) -> dict:
    row = (await session.execute(
        text(
            """
            INSERT INTO messages (conversation_id, role, content, redacted_content, inference_log_id)
            VALUES (:conv, :role, :content, :redacted, CAST(NULLIF(:log,'') AS UUID))
            RETURNING id, role, content, redacted_content, inference_log_id, created_at
            """
        ),
        {
            "conv": conv_id,
            "role": role,
            "content": content,
            "redacted": redacted_content,
            "log": inference_log_id or "",
        },
    )).mappings().one()
    await session.execute(
        text("UPDATE conversations SET updated_at = now() WHERE id = :id"),
        {"id": conv_id},
    )
    await session.commit()
    return dict(row)


async def update_status(session: AsyncSession, conv_id: UUID, status: str) -> None:
    await session.execute(
        text("UPDATE conversations SET status = :s, updated_at = now() WHERE id = :id"),
        {"s": status, "id": conv_id},
    )
    await session.commit()


async def update_provider_model(session: AsyncSession, conv_id: UUID, provider: str, model: str) -> None:
    await session.execute(
        text(
            "UPDATE conversations SET provider = :p, model = :m, updated_at = now() "
            "WHERE id = :id"
        ),
        {"p": provider, "m": model, "id": conv_id},
    )
    await session.commit()
