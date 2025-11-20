"""Lightweight Win32 helpers."""

from __future__ import annotations

import ctypes

from PySide6 import QtWidgets

user32 = ctypes.windll.user32
SetWindowLong = user32.SetWindowLongW
GetWindowLong = user32.GetWindowLongW
SetWindowDisplayAffinity = user32.SetWindowDisplayAffinity

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11


def _hwnd(widget: QtWidgets.QWidget) -> int:
    return int(widget.winId())


def prevent_capture(widget: QtWidgets.QWidget, enabled: bool) -> None:
    hwnd = _hwnd(widget)
    SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE if enabled else WDA_NONE)


def set_taskbar_visibility(widget: QtWidgets.QWidget, visible: bool) -> None:
    hwnd = _hwnd(widget)
    style = GetWindowLong(hwnd, GWL_EXSTYLE)
    if visible:
        style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
    else:
        style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    SetWindowLong(hwnd, GWL_EXSTYLE, style)
