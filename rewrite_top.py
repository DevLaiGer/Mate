from pathlib import Path

path = Path("src/mate/ui/shell.py")
text = path.read_text()
needle = "class SilentWebView"
idx = text.index(needle)
rest = text[idx:]
header = """"""Main PySide shell."""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWebEngineWidgets, QtWidgets
from PySide6.QtWebEngineCore import QWebEnginePage

from mate.config import MateSettings
from mate.core.events import EventBus
from mate.core.state import CaptionFrame, RuntimeState
from mate.ui.widgets import TitleBar
from mate.utils import win32


class SilentWebView(QtWebEngineWidgets.QWebEngineView):
    \"\"\"Suppress noisy console output coming from remote web pages.\"\"\"

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        page = self.page()
        if hasattr(page, \"setLinkDelegationPolicy\"):
            page.setLinkDelegationPolicy(QWebEnginePage.DelegateAllLinks)
            page.linkClicked.connect(self.setUrl)


"""
path.write_text(header + rest)
