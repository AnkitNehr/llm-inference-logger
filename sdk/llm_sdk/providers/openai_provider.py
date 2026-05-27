from __future__ import annotations
import os
from typing import AsyncIterator, Optional

from ..models import ChatMessage
from .base import Provider, StreamChunk


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=self.api_key)
        return self._client

    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        cancel_event: Optional[object] = None,
    ) -> AsyncIterator[StreamChunk]:
        client = self._get_client()
        stream = await client.chat.completions.create(
            model=model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            stream=True,
            stream_options={"include_usage": True},
        )
        async for event in stream:
            if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                try:
                    await stream.close()
                except Exception:
                    pass
                return
            usage = getattr(event, "usage", None)
            if event.choices:
                delta = event.choices[0].delta
                text = (delta.content or "") if delta else ""
                if text:
                    yield StreamChunk(delta=text)
            if usage is not None:
                yield StreamChunk(
                    done=True,
                    prompt_tokens=getattr(usage, "prompt_tokens", None),
                    completion_tokens=getattr(usage, "completion_tokens", None),
                    total_tokens=getattr(usage, "total_tokens", None),
                )
                return
        # Stream ended without a usage chunk
        yield StreamChunk(done=True)
