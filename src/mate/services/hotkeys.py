"""Global hotkey layer."""

from __future__ import annotations

import threading
from collections.abc import Callable

import keyboard

from mate.config import HotkeyBinding, HotkeySettings
from mate.core.events import EventBus
from mate.logging import get_logger

HotkeyCallback = Callable[[HotkeyBinding], None]


class HotkeyManager:
    def __init__(self, settings: HotkeySettings, events: EventBus) -> None:
        self.settings = settings
        self.events = events
        self.logger = get_logger("hotkeys")
        self._callbacks: dict[str, HotkeyCallback] = {}
        self._lock = threading.RLock()
        self._registered: list[str] = []

    def register_callback(self, action: str, callback: HotkeyCallback) -> None:
        self._callbacks[action] = callback

    def start(self) -> None:
        if not self.settings.enabled:
            return
        for binding in self.settings.bindings:
            keyboard.add_hotkey(binding.shortcut, lambda b=binding: self._trigger(b))
            self._registered.append(binding.shortcut)
        self.logger.info("Registered %d hotkeys", len(self.settings.bindings))

    def stop(self) -> None:
        for shortcut in self._registered:
            keyboard.remove_hotkey(shortcut)
        self._registered.clear()

    def _trigger(self, binding: HotkeyBinding) -> None:
        self.logger.info("Hotkey {} fired", binding.name)
        self.events.emit("hotkey.triggered", binding)
        callback = self._callbacks.get(binding.action)
        if callback:
            callback(binding)
