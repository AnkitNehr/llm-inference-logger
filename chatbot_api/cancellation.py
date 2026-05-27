"""In-memory cancellation registry.

Single-process only — fine for the demo. For multi-replica deployment
this would move to Redis pub/sub.
"""
import asyncio
from typing import Dict

_events: Dict[str, asyncio.Event] = {}


def register(conv_id: str) -> asyncio.Event:
    ev = asyncio.Event()
    _events[conv_id] = ev
    return ev


def cancel(conv_id: str) -> bool:
    ev = _events.get(conv_id)
    if ev is None:
        return False
    ev.set()
    return True


def release(conv_id: str) -> None:
    _events.pop(conv_id, None)
