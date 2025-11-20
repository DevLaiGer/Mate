"""Main PySide shell."""
from __future__ import annotations

import queue

from PySide6 import QtCore, QtGui, QtWebEngineWidgets, QtWidgets
from PySide6.QtWebEngineCore import QWebEnginePage

from mate.config import MateSettings
from mate.core.events import EventBus
from mate.core.state import CaptionFrame, RuntimeState
from mate.logging import get_logger
from mate.ui.widgets import TitleBar
from mate.utils import win32


class SilentWebView(QtWebEngineWidgets.QWebEngineView):
    """Suppress noisy console output coming from remote web pages."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        page = self.page()
        if hasattr(page, "setLinkDelegationPolicy"):
            page.setLinkDelegationPolicy(QWebEnginePage.DelegateAllLinks)
            page.linkClicked.connect(self.setUrl)

    def javaScriptConsoleMessage(self, level, message, line, source_id):  # noqa: N802
        # Drop Bing's preload/permission warnings to keep our console clean.
        return

    def createWindow(self, _type):  # noqa: N802
        """Capture target=_blank navigations and reuse this view."""
        popup = QtWebEngineWidgets.QWebEngineView(self)

        def _relay(url: QtCore.QUrl) -> None:
            self.setUrl(url)
            popup.deleteLater()

        popup.urlChanged.connect(_relay)
        return popup


class MainWindow(QtWidgets.QWidget):
    def __init__(self, settings: MateSettings, events: EventBus, state: RuntimeState) -> None:
        super().__init__()
        self.settings = settings
        self.events = events
        self.state = state
        self.logger = get_logger("ui.shell")
        self._device_status = {
            "mic": self._device_value(self.settings.audio.mic_device, role="mic"),
            "speaker": self._device_value(self.settings.audio.speaker_device, role="speaker"),
        }
        self._level_bars: dict[str, QtWidgets.QProgressBar] = {}
        # Track partial items per channel to avoid conflicts
        self._current_partial_items: dict[str, QtWidgets.QListWidgetItem | None] = {
            "mic": None,
            "speaker": None,
        }
        self._caption_queue: queue.Queue[CaptionFrame] = queue.Queue()

        self._setup_window()
        self._build_layout()
        self._wire_events()
        self._apply_styles()
        self._start_caption_processor()

    def _setup_window(self) -> None:
        self.setWindowTitle("mate — stealth companion")
        flags = QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.Tool
        if self.settings.ui.always_on_top:
            flags |= QtCore.Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(self.settings.ui.opacity)
        self.resize(1100, 640)

    def _build_layout(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 12)
        outer.setSpacing(12)

        self.overlay = QtWidgets.QFrame()
        self.overlay.setObjectName("Overlay")
        overlay_layout = QtWidgets.QVBoxLayout(self.overlay)
        overlay_layout.setContentsMargins(20, 0, 20, 20)
        overlay_layout.setSpacing(16)
        outer.addWidget(self.overlay)

        self.title_bar = TitleBar("mate — stealth companion", self)
        self.title_bar.minimized.connect(self.showMinimized)
        self.title_bar.closed.connect(self.close)
        self.title_bar.toggled.connect(self._toggle_max_restore)
        overlay_layout.addWidget(self.title_bar)

        overlay_layout.addLayout(self._build_controls())
        overlay_layout.addWidget(self._build_splitter(), 1)
        overlay_layout.addWidget(self._build_status_strip())

    def _build_controls(self) -> QtWidgets.QLayout:
        layout = QtWidgets.QHBoxLayout()
        layout.setSpacing(12)

        self.opacity_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(20, 100)
        self.opacity_slider.setValue(int(self.settings.ui.opacity * 100))
        self.opacity_slider.valueChanged.connect(self._handle_opacity_change)

        self.theme_combo = QtWidgets.QComboBox()
        self.theme_combo.addItems(["light", "dark"])
        self.theme_combo.setCurrentText(self.settings.ui.theme)
        self.theme_combo.currentTextChanged.connect(self._handle_theme_change)

        layout.addWidget(QtWidgets.QLabel("Opacity"))
        layout.addWidget(self.opacity_slider, 1)
        layout.addWidget(QtWidgets.QLabel("Theme"))
        layout.addWidget(self.theme_combo)
        return layout

    def _build_splitter(self) -> QtWidgets.QSplitter:
        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Orientation.Horizontal)

        self.caption_list = QtWidgets.QListWidget()
        self.caption_list.setObjectName("CaptionList")
        self.caption_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.caption_list.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.caption_list.customContextMenuRequested.connect(self._show_caption_context_menu)
        self.caption_list.setWordWrap(True)
        self.caption_list.setTextElideMode(QtCore.Qt.TextElideMode.ElideNone)
        # Disable uniform item sizes to allow variable heights
        self.caption_list.setUniformItemSizes(False)
        # Enable dynamic resizing
        self.caption_list.setResizeMode(QtWidgets.QListWidget.ResizeMode.Adjust)
        self.caption_list.addItem("mate is listening…")
        
        # Add keyboard shortcut for copying
        copy_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+C"), self.caption_list)
        copy_shortcut.activated.connect(self._copy_selected_captions)

        # Create web browser container with URL bar
        web_container = QtWidgets.QWidget()
        web_layout = QtWidgets.QVBoxLayout(web_container)
        web_layout.setContentsMargins(0, 0, 0, 0)
        web_layout.setSpacing(8)

        # URL input bar
        url_bar_container = QtWidgets.QWidget()
        url_bar_container.setObjectName("UrlBar")
        url_bar_layout = QtWidgets.QHBoxLayout(url_bar_container)
        url_bar_layout.setContentsMargins(8, 8, 8, 8)
        url_bar_layout.setSpacing(8)

        # Back button
        back_button = QtWidgets.QPushButton("←")
        back_button.setObjectName("BackButton")
        back_button.setToolTip("Go back")
        back_button.clicked.connect(self._navigate_back)
        back_button.setFixedWidth(40)

        self.url_input = QtWidgets.QLineEdit()
        self.url_input.setPlaceholderText("Enter URL and press Enter...")
        self.url_input.setText(self.settings.web.start_url)
        self.url_input.returnPressed.connect(self._navigate_to_url)

        go_button = QtWidgets.QPushButton("Go")
        go_button.setObjectName("GoButton")
        go_button.clicked.connect(self._navigate_to_url)
        go_button.setFixedWidth(60)

        url_bar_layout.addWidget(back_button)
        url_bar_layout.addWidget(self.url_input)
        url_bar_layout.addWidget(go_button)

        # Web view
        self.web_view = SilentWebView()
        self.web_view.setUrl(QtCore.QUrl(self.settings.web.start_url))
        self.web_view.urlChanged.connect(self._on_url_changed)

        web_layout.addWidget(url_bar_container)
        web_layout.addWidget(self.web_view)

        splitter.addWidget(self.caption_list)
        splitter.addWidget(web_container)
        splitter.setSizes([350, 650])
        return splitter

    def _build_status_strip(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QFrame()
        widget.setObjectName("StatusStrip")
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        self.status_label = QtWidgets.QLabel("Awaiting signals…")
        layout.addWidget(self.status_label)
        mic_widget, mic_bar = self._create_meter("Mic")
        layout.addWidget(mic_widget)
        self._level_bars["mic"] = mic_bar

        speaker_widget, speaker_bar = self._create_meter("Speaker")
        layout.addWidget(speaker_widget)
        self._level_bars["speaker"] = speaker_bar

        layout.addStretch(1)
        self.device_label = QtWidgets.QLabel(self._format_device_text())
        self.device_label.setObjectName("DeviceLabel")
        layout.addWidget(self.device_label)
        return widget

    def _create_meter(self, title: str) -> tuple[QtWidgets.QWidget, QtWidgets.QProgressBar]:
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(4)

        label = QtWidgets.QLabel(title)
        label.setObjectName("LevelLabel")
        container_layout.addWidget(label, alignment=QtCore.Qt.AlignmentFlag.AlignHCenter)

        bar = QtWidgets.QProgressBar()
        bar.setObjectName("LevelBar")
        bar.setRange(0, 100)
        bar.setTextVisible(False)
        bar.setFixedWidth(90)
        container_layout.addWidget(bar)
        return container, bar

    def _wire_events(self) -> None:
        self.events.subscribe("caption.frame", self._on_caption_frame)
        self.events.subscribe("snippet.used", self._on_snippet_used)
        self.events.subscribe("audio.level", self._on_audio_level)
        self.events.subscribe("audio.devices", self._on_audio_devices)
        if self.settings.privacy.prevent_capture:
            win32.prevent_capture(self, True)
        win32.set_taskbar_visibility(self, not self.settings.privacy.hide_from_taskbar)

    def _apply_styles(self) -> None:
        text = "#0f172a" if self.settings.ui.theme == "light" else "#f8fafc"
        overlay_bg = "#f1f5f9" if self.settings.ui.theme == "light" else "#111827"
        title_bg = "#fee2e2"
        button_bg = "#f97316"
        caption_bg = "#e0f2fe"
        splitter_bg = "#ede9fe"
        toolbar_bg = "#fef9c3"
        status_bg = "#dcfce7"

        self.overlay.setStyleSheet(
            f"""
            QWidget {{
                color: {text};
                font-family: 'Segoe UI';
                font-size: 14px;
            }}
            #Overlay {{
                background: {overlay_bg};
                border-radius: {self.settings.ui.border_radius}px;
                border: 1px solid #cbd5f5;
            }}
            #TitleBar {{
                background: {title_bg};
                border-radius: 18px;
                padding: 4px 8px;
            }}
            #TitleButton {{
                background: {button_bg};
                border: none;
                border-radius: 6px;
                color: white;
            }}
            #Toolbar {{
                background: {toolbar_bg};
                border-radius: 16px;
                padding: 8px 12px;
            }}
            #CaptionList {{
                background: {caption_bg};
                border: 1px solid #93c5fd;
                border-radius: 16px;
            }}
            QSplitter::handle {{
                background: {splitter_bg};
                margin: 4px;
                width: 6px;
                border-radius: 3px;
            }}
            #StatusStrip {{
                background: {status_bg};
                border-radius: 20px;
                border: 1px solid #86efac;
            }}
            QLabel#LevelLabel {{
                font-size: 12px;
                color: #475569;
            }}
            QProgressBar#LevelBar {{
                background: rgba(255, 255, 255, 0.6);
                border-radius: 8px;
                border: 1px solid #cbd5f5;
                height: 10px;
            }}
            QProgressBar#LevelBar::chunk {{
                background: #34d399;
                border-radius: 8px;
            }}
            QPushButton#PrimaryButton {{
                background: #a855f7;
                color: white;
                border-radius: 10px;
                padding: 6px 14px;
            }}
            QPushButton#GhostButton {{
                background: #fcd34d;
                color: #92400e;
                border-radius: 10px;
                border: none;
                padding: 6px 14px;
            }}
            #UrlBar {{
                background: #fef3c7;
                border-radius: 12px;
                border: 1px solid #fbbf24;
            }}
            QLineEdit {{
                background: white;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border: 2px solid #3b82f6;
            }}
            QPushButton#BackButton {{
                background: #6366f1;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 16px;
            }}
            QPushButton#BackButton:hover {{
                background: #4f46e5;
            }}
            QPushButton#BackButton:disabled {{
                background: #cbd5e1;
                color: #94a3b8;
            }}
            QPushButton#GoButton {{
                background: #10b981;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton#GoButton:hover {{
                background: #059669;
            }}
            """
        )

    def _on_caption_frame(self, frame: CaptionFrame) -> None:
        self.logger.info(
            "Caption frame received: speaker={} partial={} text={}",
            frame.speaker,
            frame.is_partial,
            frame.text,
        )
        # Put frame in queue - will be processed by GUI thread timer
        try:
            self._caption_queue.put_nowait(frame)
            self.logger.debug("Caption frame queued for UI update")
        except queue.Full:
            self.logger.warning("Caption queue full, dropping frame")

    def _start_caption_processor(self) -> None:
        """Start a timer to process caption frames from queue on GUI thread."""
        timer = QtCore.QTimer(self)
        timer.timeout.connect(self._process_caption_queue)
        timer.start(50)  # Check queue every 50ms
        self.logger.debug("Caption processor timer started")

    def _process_caption_queue(self) -> None:
        """Process all pending caption frames from queue (runs on GUI thread)."""
        processed = 0
        while True:
            try:
                frame = self._caption_queue.get_nowait()
                self.logger.info("Processing queued caption: {}", frame.text)
                self._append_caption(frame)
                processed += 1
            except queue.Empty:
                break
        if processed > 0:
            self.logger.debug("Processed {} caption frames from queue", processed)

    def _append_caption(self, frame: CaptionFrame) -> None:
        self.logger.info("_append_caption called with text: {}", getattr(frame, "text", "N/A"))
        try:
            if not hasattr(self, "caption_list") or self.caption_list is None:
                self.logger.error("caption_list widget not initialized!")
                return
            speaker = getattr(frame, "speaker", "unknown")
            channel = getattr(frame, "channel", "mic")
            text = getattr(frame, "text", "")
            is_partial = bool(getattr(frame, "is_partial", False))
            confidence = getattr(frame, "confidence", None)
            if confidence is None:
                confidence = 0.0

            text = "" if text is None else str(text)
            self.logger.info(
                "Appending caption to UI: speaker={} channel={} partial={} text={!r} conf={:.2f}",
                speaker,
                channel,
                is_partial,
                text,
                confidence,
            )

            label_text = f"[{speaker}] {text}"
            if is_partial:
                label_text += " …"
                item = self._current_partial_items.get(channel)
                if item is None:
                    item = QtWidgets.QListWidgetItem()
                    self.caption_list.addItem(item)  # Add to bottom
                    self._current_partial_items[channel] = item
                    # Create and set custom widget with word wrap
                    widget = self._create_caption_widget(label_text, is_partial=True)
                    self.caption_list.setItemWidget(item, widget)
                    self._update_item_height(item, widget)
                else:
                    # Update existing widget
                    widget = self.caption_list.itemWidget(item)
                    if widget:
                        label = widget.findChild(QtWidgets.QLabel)
                        if label:
                            label.setText(label_text)
                            self._style_caption_label(label, is_partial=True)
                            self._update_item_height(item, widget)
            else:
                if self._current_partial_items.get(channel) is not None:
                    item = self._current_partial_items[channel]
                    self._current_partial_items[channel] = None
                    # Update existing widget to final style
                    widget = self.caption_list.itemWidget(item)
                    if widget:
                        label = widget.findChild(QtWidgets.QLabel)
                        if label:
                            label.setText(label_text)
                            self._style_caption_label(label, is_partial=False)
                            self._update_item_height(item, widget)
                else:
                    item = QtWidgets.QListWidgetItem()
                    self.caption_list.addItem(item)  # Add to bottom
                    # Create and set custom widget with word wrap
                    widget = self._create_caption_widget(label_text, is_partial=False)
                    self.caption_list.setItemWidget(item, widget)
                    self._update_item_height(item, widget)

            self.caption_list.setCurrentItem(item)
            self.caption_list.scrollToItem(item, QtWidgets.QAbstractItemView.PositionAtBottom)
            self.caption_list.repaint()
            self.logger.info(
                "Caption inserted into UI widget: list_count={} visible={}",
                self.caption_list.count(),
                self.caption_list.isVisible(),
            )
            try:
                self.status_label.setText(f"Confidence {float(confidence) * 100:.0f}%")
            except Exception:
                self.status_label.setText("Confidence N/A")

            max_items = 200
            while self.caption_list.count() > max_items:
                self.caption_list.takeItem(0)  # Remove oldest item from top
        except Exception as exc:  # pragma: no cover - UI error logging
            self.logger.exception("Failed to append caption: %s", exc)

    def _on_snippet_used(self, snippet) -> None:
        self.status_label.setText(f"Expanded {snippet.trigger}")

    def _on_audio_level(self, payload: dict[str, float]) -> None:
        channel = payload.get("channel")
        rms = payload.get("rms")
        if channel not in self._level_bars or rms is None:
            return
        value = max(0, min(int(rms * 100), 100))
        QtCore.QTimer.singleShot(0, lambda c=channel, v=value: self._set_meter_value(c, v))

    def _on_audio_devices(self, info: dict[str, str]) -> None:
        mic = info.get("mic") or self._device_status["mic"]
        speaker = info.get("speaker") or self._device_status["speaker"]
        QtCore.QTimer.singleShot(0, lambda m=mic, s=speaker: self._set_device_label(m, s))

    def _handle_opacity_change(self, value: int) -> None:
        self.setWindowOpacity(value / 100)

    def _handle_theme_change(self, theme: str) -> None:
        self.settings.ui.theme = theme
        self._apply_styles()

    def _toggle_max_restore(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    @QtCore.Slot()
    def _toggleVisibilitySafe(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if self.settings.privacy.stealth_mode:
            win32.prevent_capture(self, True)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802
        """Handle window resize to update caption item heights."""
        super().resizeEvent(event)
        # Recalculate all caption item heights for proper text wrapping
        for i in range(self.caption_list.count()):
            item = self.caption_list.item(i)
            if item:
                widget = self.caption_list.itemWidget(item)
                if widget:
                    self._update_item_height(item, widget)

    def _navigate_to_url(self) -> None:
        """Navigate to the URL entered in the URL input box."""
        url_text = self.url_input.text().strip()
        if not url_text:
            return
        
        # Add https:// if no protocol specified
        if not url_text.startswith(("http://", "https://")):
            url_text = "https://" + url_text
        
        self.web_view.setUrl(QtCore.QUrl(url_text))
        self.logger.info("Navigating to URL: {}", url_text)

    def _navigate_back(self) -> None:
        """Navigate back in browser history."""
        if self.web_view.history().canGoBack():
            self.web_view.back()
            self.logger.info("Navigating back in browser history")

    def _on_url_changed(self, url: QtCore.QUrl) -> None:
        """Update the URL input box when the web view URL changes."""
        self.url_input.setText(url.toString())

    def _show_caption_context_menu(self, position: QtCore.QPoint) -> None:
        """Show context menu for caption list."""
        item = self.caption_list.itemAt(position)
        if item is None:
            return

        menu = QtWidgets.QMenu(self)
        copy_action = menu.addAction("Copy Caption")
        copy_all_action = menu.addAction("Copy All Captions")
        menu.addSeparator()
        clear_action = menu.addAction("Clear All Captions")

        action = menu.exec(self.caption_list.mapToGlobal(position))

        if action == copy_action:
            self._copy_selected_captions()
        elif action == copy_all_action:
            self._copy_all_captions()
        elif action == clear_action:
            self._clear_all_captions()

    def _copy_selected_captions(self) -> None:
        """Copy selected caption(s) to clipboard."""
        selected_items = self.caption_list.selectedItems()
        if not selected_items:
            return

        texts = []
        for item in selected_items:
            widget = self.caption_list.itemWidget(item)
            if widget:
                label = widget.findChild(QtWidgets.QLabel)
                if label:
                    texts.append(label.text())
            elif item.text():  # Fallback for non-widget items
                texts.append(item.text())
        
        text = "\n".join(texts)
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(text)
        self.status_label.setText(f"Copied {len(selected_items)} caption(s)")

    def _copy_all_captions(self) -> None:
        """Copy all captions to clipboard."""
        captions = []
        for i in range(self.caption_list.count()):
            item = self.caption_list.item(i)
            if item:
                widget = self.caption_list.itemWidget(item)
                if widget:
                    label = widget.findChild(QtWidgets.QLabel)
                    if label:
                        captions.append(label.text())
                elif item.text():  # Fallback for non-widget items
                    captions.append(item.text())

        text = "\n".join(captions)
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(text)
        self.status_label.setText(f"Copied all {len(captions)} captions")

    def _clear_all_captions(self) -> None:
        """Clear all captions from the list."""
        self.caption_list.clear()
        self.caption_list.addItem("mate is listening…")
        self.status_label.setText("Captions cleared")

    def _set_meter_value(self, channel: str, value: int) -> None:
        bar = self._level_bars.get(channel)
        if bar is None:
            return
        bar.setValue(value)

    def _device_value(self, configured: str | None, role: str) -> str:
        if configured:
            return configured
        return "System default mic" if role == "mic" else "Speaker loopback disabled"

    def _format_device_text(self, mic: str | None = None, speaker: str | None = None) -> str:
        mic_label = mic or self._device_status["mic"]
        speaker_label = speaker or self._device_status["speaker"]
        return f"Mic: {mic_label} • Speaker: {speaker_label}"

    def _set_device_label(self, mic: str, speaker: str) -> None:
        self._device_status["mic"] = mic
        self._device_status["speaker"] = speaker
        self.device_label.setText(self._format_device_text(mic, speaker))

    def _create_caption_widget(self, text: str, is_partial: bool) -> QtWidgets.QWidget:
        """Create a custom widget for a caption with word wrapping."""
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(0)
        
        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        # Set size policy to allow the label to expand vertically
        label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding
        )
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop)
        self._style_caption_label(label, is_partial)
        
        layout.addWidget(label)
        container.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding
        )
        return container

    def _style_caption_label(self, label: QtWidgets.QLabel, is_partial: bool) -> None:
        """Style a caption label based on whether it's partial or final."""
        font = label.font()
        font.setItalic(is_partial)
        label.setFont(font)
        
        if is_partial:
            label.setStyleSheet("color: #475569;")
        else:
            label.setStyleSheet("")

    def _update_item_height(self, item: QtWidgets.QListWidgetItem, widget: QtWidgets.QWidget) -> None:
        """Calculate and set appropriate height for multi-line text widget."""
        # Get the label from the widget
        label = widget.findChild(QtWidgets.QLabel)
        if not label:
            return
        
        # Calculate required height based on text content
        list_width = self.caption_list.viewport().width() - 20  # Use viewport width
        
        # Calculate text height with word wrap
        font_metrics = QtGui.QFontMetrics(label.font())
        text_rect = font_metrics.boundingRect(
            QtCore.QRect(0, 0, list_width - 16, 0),  # Subtract margins
            QtCore.Qt.TextFlag.TextWordWrap | QtCore.Qt.AlignmentFlag.AlignLeft,
            label.text()
        )
        
        # Set height with padding (layout margins are 8px top + 8px bottom)
        height = max(36, text_rect.height() + 16)
        
        # Update widget and item size
        widget.setMinimumHeight(height)
        widget.setMaximumHeight(height)
        item.setSizeHint(QtCore.QSize(list_width, height))
