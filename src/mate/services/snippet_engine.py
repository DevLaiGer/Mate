"""Base snippet replacement service."""

from __future__ import annotations

import threading
from dataclasses import dataclass

import keyboard

from mate.config import SnippetSettings
from mate.core.events import EventBus
from mate.logging import get_logger


@dataclass(slots=True)
class Snippet:
    trigger: str
    replacement: str


class SnippetEngine:
    def __init__(self, settings: SnippetSettings, events: EventBus) -> None:
        self.settings = settings
        self.events = events
        self.logger = get_logger("snippet-engine")
        self._snippets: list[Snippet] = [
            Snippet(**item) for item in settings.defaults
        ]
        self._buffer: str = ""
        self._lock = threading.RLock()
        self._listening = False

    def start(self) -> None:
        if not self.settings.enabled or self._listening:
            return
        self.logger.info("Snippet engine armed with %d snippets", len(self._snippets))
        keyboard.on_press(self._handle_key)
        self._listening = True

    def stop(self) -> None:
        if not self._listening:
            return
        keyboard.unhook_all()
        self._listening = False

    def register(self, trigger: str, replacement: str) -> None:
        self._snippets.append(Snippet(trigger=trigger, replacement=replacement))

    def _handle_key(self, event: keyboard.KeyboardEvent) -> None:
        if event.event_type != "down" or len(event.name or "") != 1:
            return
        with self._lock:
            self._buffer = (self._buffer + event.name)[-self.settings.max_buffer :]
            match = next((s for s in self._snippets if self._buffer.endswith(s.trigger)), None)
            if match:
                self._perform_replacement(match)
                self._buffer = ""

    def _perform_replacement(self, snippet: Snippet) -> None:
        self.logger.info("Expanding snippet {}", snippet.trigger)
        for _ in range(len(snippet.trigger)):
            keyboard.send("backspace")
        keyboard.write(snippet.replacement, delay=0.005)
        self.events.emit("snippet.used", snippet)
