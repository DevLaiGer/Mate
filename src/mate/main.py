"""mate GUI entrypoint."""

from __future__ import annotations

import os
import sys

# Disable Windows media controls before importing QtWebEngine
# This must be done before any QtWebEngine modules are imported
os.environ.setdefault("QT_WEBENGINE_DISABLE_MEDIA_KEYS", "1")
# Suppress JavaScript console output, SSL errors, and disable media key handling
chromium_flags = (
    "--disable-features=HardwareMediaKeyHandling "
    "--disable-logging "
    "--silent-debugger-extension-api "
    "--disable-background-networking "
    "--log-level=3 "
    "--disable-gpu-logging "
    "--disable-dev-shm-usage "
    "--no-sandbox"
)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", chromium_flags)

from PySide6 import QtCore, QtWidgets

from mate.config import MateSettings, load_settings
from mate.core.app import build_context
from mate.logging import configure_logging, get_logger
from mate.ui.shell import MainWindow
from mate.utils.process import SingleInstance


def main() -> None:
    settings: MateSettings = load_settings()
    configure_logging(settings)
    logger = get_logger("main")

    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    with SingleInstance(settings.paths.base_dir / "mate.lock"):
        ctx = build_context(settings)

        window = MainWindow(settings, ctx.events, ctx.state, ctx)

        def hide_window(binding) -> None:  # noqa: ARG001
            QtCore.QMetaObject.invokeMethod(
                window,
                "_hideWindowSafe",
                QtCore.Qt.ConnectionType.QueuedConnection,
            )

        def show_window(binding) -> None:  # noqa: ARG001
            QtCore.QMetaObject.invokeMethod(
                window,
                "_showWindowSafe",
                QtCore.Qt.ConnectionType.QueuedConnection,
            )

        def panic_hide(binding) -> None:  # noqa: ARG001
            QtCore.QMetaObject.invokeMethod(
                window,
                "_panicQuitSafe",
                QtCore.Qt.ConnectionType.QueuedConnection,
            )

        def mute_audio(binding) -> None:  # noqa: ARG001
            QtCore.QMetaObject.invokeMethod(
                window,
                "_muteAudioSafe",
                QtCore.Qt.ConnectionType.QueuedConnection,
            )

        def unmute_audio(binding) -> None:  # noqa: ARG001
            QtCore.QMetaObject.invokeMethod(
                window,
                "_unmuteAudioSafe",
                QtCore.Qt.ConnectionType.QueuedConnection,
            )

        def increase_opacity(binding) -> None:  # noqa: ARG001
            QtCore.QMetaObject.invokeMethod(
                window,
                "_increaseOpacitySafe",
                QtCore.Qt.ConnectionType.QueuedConnection,
            )

        def decrease_opacity(binding) -> None:  # noqa: ARG001
            QtCore.QMetaObject.invokeMethod(
                window,
                "_decreaseOpacitySafe",
                QtCore.Qt.ConnectionType.QueuedConnection,
            )

        def toggle_view(binding) -> None:  # noqa: ARG001
            QtCore.QMetaObject.invokeMethod(
                window,
                "_toggleViewSafe",
                QtCore.Qt.ConnectionType.QueuedConnection,
            )

        ctx.hotkeys.register_callback("hide_window", hide_window)
        ctx.hotkeys.register_callback("show_window", show_window)
        ctx.hotkeys.register_callback("panic_hide", panic_hide)
        ctx.hotkeys.register_callback("mute_audio", mute_audio)
        ctx.hotkeys.register_callback("unmute_audio", unmute_audio)
        ctx.hotkeys.register_callback("increase_opacity", increase_opacity)
        ctx.hotkeys.register_callback("decrease_opacity", decrease_opacity)
        ctx.hotkeys.register_callback("toggle_view", toggle_view)

        # Set Qt app for thread-safe hotkey callbacks
        ctx.hotkeys.set_qt_app(app)

        ctx.start()
        window.show()
        logger.info("mate ready")
        sys.exit(app.exec())


if __name__ == "__main__":
    main()
