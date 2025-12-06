"""Native Win32 hotkey registration service."""

from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable

import win32con
import win32gui
from PySide6 import QtCore

from mate.logging import get_logger

user32 = ctypes.windll.user32

# Win32 Modifier Flags (matching hotkey_parser)
MOD_NONE = 0x0000
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

# Win32 Messages
WM_HOTKEY = 0x0312

logger = get_logger("win32_hotkeys")


class MessageProcessor(QtCore.QObject):
    """Qt object to process Windows messages in the main thread."""

    def __init__(self, service: Win32HotkeyService) -> None:
        super().__init__()
        self._service = service
        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._process_messages)
        self._timer.start(10)  # Check every 10ms

    def _process_messages(self) -> None:
        """Process Windows messages."""
        self._service.process_messages()


class Win32HotkeyService:
    """Native Win32 hotkey registration service using RegisterHotKey API."""

    def __init__(self) -> None:
        self._hotkeys: dict[int, Callable[[], None]] = {}
        self._next_id = 0x0000B000  # Start from a safe range to avoid conflicts
        self._lock = threading.RLock()
        self._hwnd: int | None = None
        self._running = False
        self._qt_app: QtCore.QCoreApplication | None = None
        self._message_processor: MessageProcessor | None = None

    def set_qt_app(self, app: QtCore.QCoreApplication) -> None:
        """Set the Qt application instance for thread-safe callback dispatch."""
        self._qt_app = app

    def start(self) -> None:
        """Start the hotkey service and create message window."""
        with self._lock:
            if self._running:
                return

            # Create a message-only window
            class_name = f"MateHotkeyWindow_{int(time.time() * 1000)}"
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self._window_proc
            wc.lpszClassName = class_name
            wc.hInstance = win32gui.GetModuleHandle(None)

            try:
                class_atom = win32gui.RegisterClass(wc)
            except Exception as e:
                # Class might already be registered (shouldn't happen with unique name, but handle gracefully)
                error_code = ctypes.get_last_error()
                if error_code == 1410:  # ERROR_CLASS_ALREADY_EXISTS
                    logger.warning("Window class already exists, attempting to use existing")
                    # Try to find existing window
                    existing = win32gui.FindWindow(class_name, None)
                    if existing:
                        self._hwnd = existing
                        self._running = True
                        logger.info("Using existing hotkey window")
                        return
                logger.error(f"Failed to register window class: {e}, error={error_code}")
                raise

            self._hwnd = win32gui.CreateWindowEx(
                0,
                class_atom,
                "Mate Hotkey Window",
                0,
                0,
                0,
                0,
                0,
                win32con.HWND_MESSAGE,  # Message-only window
                0,
                wc.hInstance,
                None,
            )

            if not self._hwnd:
                raise RuntimeError("Failed to create hotkey message window")

            self._running = True

            # Start message processor if Qt app is available
            if self._qt_app:
                self._message_processor = MessageProcessor(self)
                logger.info("Win32 hotkey service started with Qt message processor")
            else:
                logger.info("Win32 hotkey service started (no Qt app, manual message processing required)")

    def stop(self) -> None:
        """Stop the hotkey service and unregister all hotkeys."""
        with self._lock:
            if not self._running:
                return

            # Unregister all hotkeys
            for hotkey_id in list(self._hotkeys.keys()):
                self._unregister_hotkey_internal(hotkey_id)

            self._hotkeys.clear()

            # Stop message processor
            if self._message_processor:
                self._message_processor._timer.stop()
                self._message_processor = None

            # Destroy the window
            if self._hwnd:
                win32gui.DestroyWindow(self._hwnd)
                self._hwnd = None

            self._running = False
            logger.info("Win32 hotkey service stopped")

    def register_hotkey(
        self, modifiers: int, vk_code: int, callback: Callable[[], None]
    ) -> int | None:
        """
        Register a hotkey.

        Args:
            modifiers: Win32 modifier flags (MOD_ALT, MOD_CONTROL, etc.)
            vk_code: Virtual key code
            callback: Callback function to invoke when hotkey is pressed

        Returns:
            Hotkey ID if successful, None if registration failed (e.g., conflict)
        """
        with self._lock:
            if not self._running or not self._hwnd:
                logger.error("Hotkey service not started")
                return None

            hotkey_id = self._next_id
            self._next_id += 1
            if self._next_id > 0x0000BFFF:  # Wrap around to avoid overflow
                self._next_id = 0x0000B000

            # Register the hotkey
            result = user32.RegisterHotKey(self._hwnd, hotkey_id, modifiers, vk_code)

            if not result:
                error = ctypes.get_last_error()
                if error == 1409:  # ERROR_HOTKEY_ALREADY_REGISTERED
                    logger.warning(
                        f"Hotkey already registered: modifiers=0x{modifiers:02X}, vk=0x{vk_code:02X}"
                    )
                elif error == 87:  # ERROR_INVALID_PARAMETER
                    # Some key combinations are not supported by RegisterHotKey
                    # (e.g., arrow keys with certain modifiers on some Windows versions)
                    logger.warning(
                        f"Hotkey combination not supported by Windows: modifiers=0x{modifiers:02X}, vk=0x{vk_code:02X} (error=87)"
                    )
                else:
                    logger.error(
                        f"Failed to register hotkey: error={error}, modifiers=0x{modifiers:02X}, vk=0x{vk_code:02X}"
                    )
                return None

            self._hotkeys[hotkey_id] = callback
            logger.debug(
                f"Registered hotkey ID={hotkey_id}, modifiers=0x{modifiers:02X}, vk=0x{vk_code:02X}"
            )
            return hotkey_id

    def unregister_hotkey(self, hotkey_id: int) -> bool:
        """
        Unregister a hotkey.

        Args:
            hotkey_id: Hotkey ID returned from register_hotkey

        Returns:
            True if successfully unregistered, False otherwise
        """
        with self._lock:
            return self._unregister_hotkey_internal(hotkey_id)

    def _unregister_hotkey_internal(self, hotkey_id: int) -> bool:
        """Internal unregister without lock (caller must hold lock)."""
        if hotkey_id not in self._hotkeys:
            return False

        result = user32.UnregisterHotKey(self._hwnd, hotkey_id)
        if result:
            del self._hotkeys[hotkey_id]
            logger.debug(f"Unregistered hotkey ID={hotkey_id}")
        else:
            logger.warning(f"Failed to unregister hotkey ID={hotkey_id}")

        return bool(result)

    def _window_proc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        """Window procedure to handle WM_HOTKEY messages."""
        if msg == WM_HOTKEY:
            hotkey_id = wparam
            with self._lock:
                callback = self._hotkeys.get(hotkey_id)
                if callback:
                    # Dispatch to Qt main thread if available
                    if self._qt_app:
                        QtCore.QTimer.singleShot(0, callback)
                    else:
                        # Fallback: call directly (shouldn't happen in normal operation)
                        try:
                            callback()
                        except Exception as e:
                            logger.error(f"Error in hotkey callback: {e}", exc_info=True)
            return 0

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def process_messages(self) -> None:
        """Process Windows messages. Should be called periodically from main thread."""
        if not self._running or not self._hwnd:
            return

        try:
            # PeekMessage returns (ret, hwnd, msg, wparam, lparam, time, point)
            peek_result = win32gui.PeekMessage(win32con.PM_REMOVE, self._hwnd, 0, 0)
            while peek_result[0]:  # ret != 0 means message available
                hwnd, msg, wparam, lparam = peek_result[1], peek_result[2], peek_result[3], peek_result[4]
                if msg == WM_HOTKEY:
                    self._window_proc(hwnd, msg, wparam, lparam)
                else:
                    win32gui.TranslateMessage(peek_result)
                    win32gui.DispatchMessage(peek_result)
                peek_result = win32gui.PeekMessage(win32con.PM_REMOVE, self._hwnd, 0, 0)
        except Exception as e:
            logger.debug(f"Error processing messages: {e}")

