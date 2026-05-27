"""Fire-and-forget async logger.

POSTs a LogPayload to the ingestion API. Never raises into caller code —
chat must keep working even if ingestion is down.
"""
from __future__ import annotations
import asyncio
import logging
import os
from typing import Optional

import httpx

from .models import LogPayload

log = logging.getLogger("llm_sdk.logger")


class IngestionLogger:
    def __init__(self, ingestion_url: Optional[str] = None, timeout: float = 2.0):
        self.url = (ingestion_url or os.getenv("INGESTION_URL", "http://localhost:8002")).rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def emit(self, payload: LogPayload) -> None:
        """Schedule a non-blocking send. Returns immediately."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._send(payload))
        except RuntimeError:
            # No running loop — fall back to synchronous best-effort send
            try:
                httpx.post(f"{self.url}/v1/logs", json=payload.model_dump(mode="json"), timeout=self.timeout)
            except Exception as exc:  # noqa: BLE001
                log.warning("ingestion log dropped (sync): %s", exc)

    async def _send(self, payload: LogPayload) -> None:
        try:
            client = self._get_client()
            await client.post(f"{self.url}/v1/logs", json=payload.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001
            log.warning("ingestion log dropped: %s", exc)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
