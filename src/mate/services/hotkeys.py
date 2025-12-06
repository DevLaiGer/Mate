"""Global hotkey layer."""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6 import QtCore

from mate.config import HotkeyBinding, HotkeySettings
from mate.core.events import EventBus
from mate.logging import get_logger
from mate.services.win32_hotkeys import Win32HotkeyService
from mate.utils.hotkey_parser import parse_hotkey

HotkeyCallback = Callable[[HotkeyBinding], None]


class HotkeyManager:
    def __init__(self, settings: HotkeySettings, events: EventBus) -> None:
        self.settings = settings
        self.events = events
        self.logger = get_logger("hotkeys")
        self._callbacks: dict[str, HotkeyCallback] = {}
        self._lock = threading.RLock()
        self._registered: dict[str, int] = {}
        self._win32_service: Win32HotkeyService | None = None
        self._qt_app: QtCore.QCoreApplication | None = None

    def set_qt_app(self, app: QtCore.QCoreApplication) -> None:
        """Set the Qt application instance for thread-safe operations."""
        self._qt_app = app
        if self._win32_service:
            self._win32_service.set_qt_app(app)

    def register_callback(self, action: str, callback: HotkeyCallback) -> None:
        self._callbacks[action] = callback

    def start(self) -> None:
        if not self.settings.enabled:
            self.logger.info("Hotkeys disabled in settings")
            return

        self._win32_service = Win32HotkeyService()
        if self._qt_app:
            self._win32_service.set_qt_app(self._qt_app)
        self._win32_service.start()

        registered_count = 0
        for binding in self.settings.bindings:
            try:
                parsed = parse_hotkey(binding.shortcut)
                hotkey_id = self._win32_service.register_hotkey(
                    parsed.modifiers, parsed.vk_code, lambda b=binding: self._trigger(b)
                )

                if hotkey_id is not None:
                    self._registered[binding.shortcut] = hotkey_id
                    registered_count += 1
                    self.logger.debug(f"Registered hotkey: {binding.name} ({binding.shortcut})")
                else:
                    self.logger.warning(f"Failed to register hotkey: {binding.name} ({binding.shortcut}) - may be in use")
            except ValueError as e:
                self.logger.error(f"Invalid hotkey format '{binding.shortcut}': {e}")
            except Exception as e:
                self.logger.error(f"Error registering hotkey '{binding.shortcut}': {e}", exc_info=True)

        self.logger.info(f"Hotkey manager started: {registered_count}/{len(self.settings.bindings)} hotkeys registered")

    def stop(self) -> None:
        with self._lock:
            if self._win32_service:
                for shortcut, hotkey_id in self._registered.items():
                    self._win32_service.unregister_hotkey(hotkey_id)
                self._win32_service.stop()
                self._win32_service = None

            self._registered.clear()
            self.logger.info("Hotkey manager stopped")

    def _trigger(self, binding: HotkeyBinding) -> None:
        """Trigger hotkey callback (thread-safe)."""
        self.events.emit("hotkey.triggered", binding)
        callback = self._callbacks.get(binding.action)
        if callback:
            try:
                callback(binding)
            except Exception as e:
                self.logger.error(f"Error in hotkey callback for {binding.action}: {e}", exc_info=True)
