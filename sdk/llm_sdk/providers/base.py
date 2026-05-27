from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from ..models import ChatMessage


@dataclass
class StreamChunk:
    delta: str = ""
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    done: bool = False


class Provider(ABC):
    name: str = "base"

    @abstractmethod
    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        cancel_event: Optional[object] = None,
    ) -> AsyncIterator[StreamChunk]:
        ...
