"""Reusable UI components."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


class TitleBar(QtWidgets.QWidget):
    minimized = QtCore.Signal()
    closed = QtCore.Signal()
    toggled = QtCore.Signal()

    def __init__(self, title: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self._mouse_pos = None

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        self.label = QtWidgets.QLabel(title)
        font = QtGui.QFont()
        font.setPointSize(11)
        font.setBold(True)
        self.label.setFont(font)
        layout.addWidget(self.label)
        layout.addStretch(1)

        self.btn_min = self._make_button("–")
        self.btn_toggle = self._make_button("⬒")
        self.btn_close = self._make_button("✕")

        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_toggle)
        layout.addWidget(self.btn_close)

        self.btn_min.clicked.connect(self.minimized.emit)
        self.btn_toggle.clicked.connect(self.toggled.emit)
        self.btn_close.clicked.connect(self.closed.emit)

    def _make_button(self, text: str) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton(text)
        btn.setObjectName("TitleButton")
        btn.setFixedSize(28, 24)
        return btn

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.LeftButton:
            origin = self.window().frameGeometry().topLeft()
            self._mouse_pos = event.globalPosition().toPoint() - origin
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._mouse_pos is not None and event.buttons() & QtCore.Qt.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._mouse_pos)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        self._mouse_pos = None
        super().mouseReleaseEvent(event)
