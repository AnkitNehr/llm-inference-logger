from __future__ import annotations
import os
from typing import AsyncIterator, Optional

from ..models import ChatMessage
from .base import Provider, StreamChunk


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()

    def _configure(self):
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        return genai

    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        cancel_event: Optional[object] = None,
    ) -> AsyncIterator[StreamChunk]:
        genai = self._configure()

        system_prompt = next((m.content for m in messages if m.role == "system"), None)
        gem_history = []
        for m in messages:
            if m.role == "system":
                continue
            # Gemini uses "model" instead of "assistant"
            role = "model" if m.role == "assistant" else "user"
            gem_history.append({"role": role, "parts": [m.content]})

        gen_model = genai.GenerativeModel(
            model_name=model,
            system_instruction=system_prompt or "You are a helpful, concise assistant.",
        )

        response = await gen_model.generate_content_async(gem_history, stream=True)

        prompt_tokens = completion_tokens = total_tokens = None
        async for chunk in response:
            if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                return
            text = getattr(chunk, "text", "") or ""
            if text:
                yield StreamChunk(delta=text)

        # Gather usage from the resolved response (available after streaming)
        try:
            usage = getattr(response, "usage_metadata", None)
            if usage:
                prompt_tokens = getattr(usage, "prompt_token_count", None)
                completion_tokens = getattr(usage, "candidates_token_count", None)
                total_tokens = getattr(usage, "total_token_count", None)
        except Exception:
            pass

        yield StreamChunk(
            done=True,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
