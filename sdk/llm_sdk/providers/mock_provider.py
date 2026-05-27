from __future__ import annotations
import asyncio
import random
from typing import AsyncIterator, Optional

from ..models import ChatMessage
from .base import Provider, StreamChunk


class MockProvider(Provider):
    name = "mock"

    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        cancel_event: Optional[object] = None,
    ) -> AsyncIterator[StreamChunk]:
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        reply = self._canned_reply(last_user)
        tokens = reply.split()
        prompt_tokens = sum(len(m.content.split()) for m in messages)
        for i, tok in enumerate(tokens):
            if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                return
            await asyncio.sleep(random.uniform(0.02, 0.07))
            yield StreamChunk(delta=(tok + (" " if i < len(tokens) - 1 else "")))
        yield StreamChunk(
            done=True,
            prompt_tokens=prompt_tokens,
            completion_tokens=len(tokens),
            total_tokens=prompt_tokens + len(tokens),
        )

    @staticmethod
    def _canned_reply(user_msg: str) -> str:
        snippet = user_msg.strip()[:60] or "your message"
        return (
            f"(mock provider) I received: \"{snippet}\". "
            "This is a simulated streaming response so the system works without an API key. "
            "Set OPENAI_API_KEY in .env to use the real model."
        )
