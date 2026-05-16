from __future__ import annotations

import asyncio
import threading
from typing import Any


class EventBus:
    """Cross-thread fan-out. Subscribers register an asyncio.Queue bound to
    their event loop; publishers (often background threads) schedule
    `queue.put` onto each subscriber's loop via run_coroutine_threadsafe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = []

    def subscribe(self) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        with self._lock:
            self._subs.append((q, loop))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs = [(qq, ll) for qq, ll in self._subs if qq is not q]

    def publish(self, event: Any) -> None:
        with self._lock:
            subs = list(self._subs)
        for q, loop in subs:
            try:
                asyncio.run_coroutine_threadsafe(q.put(event), loop)
            except RuntimeError:
                pass


bus = EventBus()
