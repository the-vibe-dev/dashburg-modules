from __future__ import annotations
import asyncio
import json
from typing import Any
from appgen.repo import add_outbox_event

_subscribers: list[asyncio.Queue] = []


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    if q in _subscribers:
        _subscribers.remove(q)


def emit(topic: str, payload: dict[str, Any]) -> str:
    eid = add_outbox_event(topic, payload)
    envelope = {"id": eid, "topic": topic, "payload": payload}
    for q in list(_subscribers):
        try:
            q.put_nowait(envelope)
        except Exception:
            pass
    return eid


def sse_encode(topic: str, payload: dict[str, Any]) -> str:
    return f"event: {topic}\ndata: {json.dumps(payload)}\n\n"
