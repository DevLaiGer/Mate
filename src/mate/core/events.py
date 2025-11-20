"""Thread-safe pub/sub bus for the mate runtime."""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any

EventHandler = Callable[[Any], None]


class EventBus:
    """Minimal event bus supporting background threads."""

    def __init__(self) -> None:
        self._subscribers: defaultdict[str, list[EventHandler]] = defaultdict(list)
        self._lock = threading.RLock()

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        with self._lock:
            if handler not in self._subscribers[topic]:
                self._subscribers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: EventHandler) -> None:
        with self._lock:
            if handler in self._subscribers[topic]:
                self._subscribers[topic].remove(handler)

    def emit(self, topic: str, payload: Any) -> None:
        with self._lock:
            handlers = list(self._subscribers.get(topic, ()))
        for handler in handlers:
            handler(payload)
