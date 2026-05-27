from __future__ import annotations
import os
from typing import AsyncIterator, Optional

from ..models import ChatMessage
from .base import Provider, StreamChunk


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        self._client = None

    def _get_client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        cancel_event: Optional[object] = None,
    ) -> AsyncIterator[StreamChunk]:
        client = self._get_client()
        system_prompt = next((m.content for m in messages if m.role == "system"), None)
        convo = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]

        async with client.messages.stream(
            model=model,
            system=system_prompt or "You are a helpful assistant.",
            messages=convo,
            max_tokens=1024,
        ) as stream:
            async for text in stream.text_stream:
                if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                    return
                if text:
                    yield StreamChunk(delta=text)
            final = await stream.get_final_message()
            usage = getattr(final, "usage", None)
            yield StreamChunk(
                done=True,
                prompt_tokens=getattr(usage, "input_tokens", None),
                completion_tokens=getattr(usage, "output_tokens", None),
                total_tokens=(
                    (getattr(usage, "input_tokens", 0) or 0)
                    + (getattr(usage, "output_tokens", 0) or 0)
                ) if usage else None,
            )
