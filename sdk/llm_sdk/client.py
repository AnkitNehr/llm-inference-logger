"""Thin wrapper around providers that captures inference metadata
and ships logs to the ingestion API.

Usage:
    client = LLMClient(provider="openai", model="gpt-4o-mini")
    async for chunk in client.stream_chat(messages, conversation_id="..."):
        ...
"""
from __future__ import annotations
import asyncio
import os
import time
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from .logger import IngestionLogger
from .models import ChatMessage, LogPayload
from .pii import redact
from .providers import Provider, get_provider

PREVIEW_LEN = 500


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _preview(text: str, redact_pii: bool = True) -> str:
    if not text:
        return ""
    text = redact(text) if redact_pii else text
    return text[:PREVIEW_LEN]


class LLMClient:
    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        ingestion_url: Optional[str] = None,
        redact_pii: bool = True,
    ):
        provider_name = (provider or os.getenv("DEFAULT_PROVIDER", "openai")).lower()
        # Auto-fallback to mock if the provider's key is missing
        if provider_name == "openai" and not os.getenv("OPENAI_API_KEY"):
            provider_name = "mock"
        if provider_name == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
            provider_name = "mock"
        if provider_name == "gemini" and not os.getenv("GEMINI_API_KEY"):
            provider_name = "mock"

        self.provider_name = provider_name
        self.provider: Provider = get_provider(provider_name)
        self.model = model or os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
        self.redact_pii = redact_pii
        self.logger = IngestionLogger(ingestion_url)

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        conversation_id: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
        request_id: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """Yields dicts: {'type':'token','delta':...}, {'type':'done','request_id':..., 'output':..., 'usage':...},
        {'type':'error','message':...}. Always emits a log at the end.
        """
        request_id = request_id or str(uuid.uuid4())
        started = _now()
        t0 = time.perf_counter()
        ttft_ms: Optional[int] = None
        output_chunks: list[str] = []
        prompt_tokens = completion_tokens = total_tokens = None
        status = "success"
        err_type = err_msg = None
        input_preview_text = "\n".join(f"{m.role}: {m.content}" for m in messages[-3:])

        try:
            async for chunk in self.provider.stream_chat(self.model, messages, cancel_event=cancel_event):
                if chunk.delta:
                    if ttft_ms is None:
                        ttft_ms = int((time.perf_counter() - t0) * 1000)
                    output_chunks.append(chunk.delta)
                    yield {"type": "token", "delta": chunk.delta}
                if chunk.done:
                    prompt_tokens = chunk.prompt_tokens
                    completion_tokens = chunk.completion_tokens
                    total_tokens = chunk.total_tokens
                    break
            if cancel_event is not None and cancel_event.is_set():
                status = "cancelled"
        except Exception as exc:  # noqa: BLE001
            status = "error"
            err_type = type(exc).__name__
            err_msg = str(exc)[:500]
            yield {"type": "error", "message": err_msg}
        finally:
            completed = _now()
            output_text = "".join(output_chunks)
            payload = LogPayload(
                request_id=request_id,
                conversation_id=conversation_id,
                provider=self.provider_name,
                model=self.model,
                status=status,
                error_type=err_type,
                error_message=err_msg,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                ttft_ms=ttft_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                input_preview=_preview(input_preview_text, self.redact_pii),
                output_preview=_preview(output_text, self.redact_pii),
                streamed=True,
                started_at=started,
                completed_at=completed,
                metadata={},
            )
            self.logger.emit(payload)
            yield {
                "type": "done",
                "request_id": request_id,
                "output": output_text,
                "status": status,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                },
            }

    async def aclose(self) -> None:
        await self.logger.aclose()
