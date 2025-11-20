"""mate GUI entrypoint."""

from __future__ import annotations

import sys

from PySide6 import QtCore, QtWidgets

from mate.config import MateSettings, load_settings
from mate.core.app import build_context
from mate.core.state import CaptionFrame
from mate.logging import configure_logging, get_logger
from mate.ui.shell import MainWindow
from mate.utils.process import SingleInstance


def _attach_state_mirror(ctx) -> None:
    def mirror(frame: CaptionFrame) -> None:
        ctx.state.push_caption(frame)

    ctx.events.subscribe("caption.frame", mirror)


def main() -> None:
    settings: MateSettings = load_settings()
    configure_logging(settings)
    logger = get_logger("main")

    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    with SingleInstance(settings.paths.base_dir / "mate.lock"):
        ctx = build_context(settings)
        _attach_state_mirror(ctx)

        window = MainWindow(settings, ctx.events, ctx.state)

        def _toggle_window_visibility(binding) -> None:  # noqa: ARG001
            QtCore.QMetaObject.invokeMethod(
                window,
                "_toggleVisibilitySafe",
                QtCore.Qt.ConnectionType.QueuedConnection,
            )

        def panic_hide(binding) -> None:  # noqa: ARG001
            window.hide()

        ctx.hotkeys.register_callback("toggle_overlay", _toggle_window_visibility)
        ctx.hotkeys.register_callback("toggle_visibility", _toggle_window_visibility)
        ctx.hotkeys.register_callback("panic_hide", panic_hide)

        ctx.start()
        window.show()
        logger.info("mate ready")
        sys.exit(app.exec())


if __name__ == "__main__":
    main()
