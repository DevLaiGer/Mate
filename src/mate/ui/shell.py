"""Main PySide shell."""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWebEngineWidgets, QtWidgets
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

from mate.config import MateSettings
from mate.core.events import EventBus
from mate.core.state import RuntimeState
from mate.logging import get_logger
from mate.ui.widgets import TitleBar
from mate.utils import win32


class SilentWebPage(QWebEnginePage):
    """Custom page that suppresses JavaScript console messages."""

    def javaScriptConsoleMessage(self, level, message, line, source_id):  # noqa: N802
        """Suppress all JavaScript console messages."""
        # Suppress ALL console messages unconditionally
        # Do NOT call super() to prevent any default handling
        # This includes:
        # - Permissions-Policy warnings
        # - WebGPU warnings
        # - Preload warnings
        # - Cloudflare challenge warnings
        # - Font-size/color transparent warnings
        # - CORS errors
        # - Fetch errors
        # - Analytics/telemetry warnings
        # - Any other JavaScript console output
        pass  # Explicitly do nothing


class SilentWebView(QtWebEngineWidgets.QWebEngineView):
    """Suppress noisy console output coming from remote web pages."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        # Set custom page that suppresses console messages
        self.setPage(SilentWebPage(self))
        page = self.page()
        if hasattr(page, "setLinkDelegationPolicy"):
            page.setLinkDelegationPolicy(QWebEnginePage.DelegateAllLinks)
            page.linkClicked.connect(self.setUrl)
        # Disable hardware media key handling to prevent Windows media controls
        # This allows audio playback but prevents media controls from appearing
        settings = page.settings()
        if hasattr(settings, "setAttribute"):
            # Disable hardware media key handling (similar to browser flags)
            # This prevents Windows from showing media controls in notifications
            try:
                # Allow audio to play automatically without user gesture
                if hasattr(QWebEngineSettings.WebAttribute, "PlaybackRequiresUserGesture"):
                    settings.setAttribute(
                        QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False
                    )
            except (AttributeError, TypeError):
                pass
            # Enable JavaScript (required for audio playback)
            try:
                if hasattr(QWebEngineSettings.WebAttribute, "JavascriptEnabled"):
                    settings.setAttribute(
                        QWebEngineSettings.WebAttribute.JavascriptEnabled, True
                    )
            except (AttributeError, TypeError):
                pass
        # Disable JavaScript console output via settings
        try:
            if hasattr(QWebEngineSettings.WebAttribute, "JavascriptCanOpenWindows"):
                settings.setAttribute(
                    QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False
                )
        except (AttributeError, TypeError):
            pass
        # Ensure audio is not muted by default
        if hasattr(page, "setAudioMuted"):
            page.setAudioMuted(False)

    def javaScriptConsoleMessage(self, level, message, line, source_id):  # noqa: N802
        """Override to suppress all JavaScript console messages."""
        # Suppress all console output (also handled by SilentWebPage)
        # Do NOT call super() to prevent any default handling
        pass  # Explicitly do nothing

    def createWindow(self, _type):  # noqa: N802
        """Capture target=_blank navigations and reuse this view."""
        popup = QtWebEngineWidgets.QWebEngineView(self)

        def _relay(url: QtCore.QUrl) -> None:
            self.setUrl(url)
            popup.deleteLater()

        popup.urlChanged.connect(_relay)
        return popup


class ChatGPTView(QtWidgets.QWidget):
    """Simple ChatGPT-only view with title bar and web view."""
    
    def __init__(self, parent: QtWidgets.QWidget | None = None, chatgpt_url: str = "https://www.chatgpt.com") -> None:
        super().__init__(parent)
        self._parent_window = parent
        self.web_view = SilentWebView(self)
        self._setup_ui(chatgpt_url)
        self._wire_events()
    
    def _setup_ui(self, chatgpt_url: str) -> None:
        """Set up the UI layout with overlay, title bar and web view."""
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        
        # Overlay frame (same styling as browser view)
        self.overlay = QtWidgets.QFrame()
        self.overlay.setObjectName("Overlay")
        self.overlay.setMouseTracking(True)
        overlay_layout = QtWidgets.QVBoxLayout(self.overlay)
        overlay_layout.setContentsMargins(8, 6, 8, 8)
        overlay_layout.setSpacing(6)
        
        # Title bar with window controls
        self.title_bar = TitleBar("mate — ChatGPT", self)
        if self._parent_window:
            self.title_bar.minimized.connect(self._parent_window.showMinimized)
            self.title_bar.closed.connect(self._parent_window.close)
            self.title_bar.toggled.connect(self._parent_window._toggle_max_restore)
            self.title_bar.theme_toggled.connect(self._parent_window._handle_theme_toggle)
            # Set initial theme state
            self.title_bar.set_theme(self._parent_window.settings.ui.theme)
        overlay_layout.addWidget(self.title_bar)
        
        # Web view
        overlay_layout.addWidget(self.web_view, 1)
        
        outer.addWidget(self.overlay)
    
    def _wire_events(self) -> None:
        """Wire up event handlers."""
        # Navigate to ChatGPT on initialization
        self.web_view.setUrl(QtCore.QUrl("https://www.chatgpt.com"))
    
    def ensure_audio_enabled(self) -> None:
        """Ensure web view audio is enabled and not muted."""
        page = self.web_view.page()
        if page:
            if hasattr(page, "setAudioMuted"):
                page.setAudioMuted(False)
            elif hasattr(page, "audioMuted"):
                try:
                    page.audioMuted = False
                except (AttributeError, TypeError):
                    pass
            if hasattr(self.web_view, "setAudioMuted"):
                self.web_view.setAudioMuted(False)
            elif hasattr(self.web_view, "audioMuted"):
                try:
                    self.web_view.audioMuted = False
                except (AttributeError, TypeError):
                    pass


class TabContainer(QtWidgets.QWidget):
    """Container widget for a browser tab with URL bar and web view."""
    
    url_changed = QtCore.Signal(QtCore.QUrl)
    
    def __init__(self, parent: QtWidgets.QWidget | None = None, start_url: str | None = None) -> None:
        super().__init__(parent)
        self.web_view = SilentWebView(self)
        self._setup_ui(start_url)
        self._wire_events()
    
    def _setup_ui(self, start_url: str | None) -> None:
        """Set up the UI layout with URL bar and web view."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # URL input bar
        url_bar_container = QtWidgets.QWidget()
        url_bar_container.setObjectName("UrlBar")
        url_bar_container.setFixedHeight(32)  # Fixed height for URL bar
        url_bar_layout = QtWidgets.QHBoxLayout(url_bar_container)
        url_bar_layout.setContentsMargins(6, 4, 6, 4)
        url_bar_layout.setSpacing(6)
        
        # Back button
        self.back_button = QtWidgets.QPushButton("←")
        self.back_button.setObjectName("BackButton")
        self.back_button.setToolTip("Go back")
        self.back_button.setFixedWidth(32)
        self.back_button.clicked.connect(self._navigate_back)
        
        self.url_input = QtWidgets.QLineEdit()
        self.url_input.setPlaceholderText("Enter URL and press Enter...")
        if start_url:
            self.url_input.setText(start_url)
        self.url_input.returnPressed.connect(self._navigate_to_url)
        
        go_button = QtWidgets.QPushButton("Go")
        go_button.setObjectName("GoButton")
        go_button.clicked.connect(self._navigate_to_url)
        go_button.setFixedWidth(48)
        
        url_bar_layout.addWidget(self.back_button)
        url_bar_layout.addWidget(self.url_input, 1)
        url_bar_layout.addWidget(go_button)
        
        layout.addWidget(url_bar_container)
        layout.addWidget(self.web_view, 1)
    
    def _wire_events(self) -> None:
        """Wire up event handlers."""
        self.web_view.urlChanged.connect(self._on_web_view_url_changed)
        # Update back button state initially and after navigation
        self._update_back_button()
        # Also update after back navigation completes
        self.web_view.loadFinished.connect(self._update_back_button)
    
    def _on_web_view_url_changed(self, url: QtCore.QUrl) -> None:
        """Update URL input when web view URL changes."""
        self.url_input.setText(url.toString())
        self.url_changed.emit(url)
        self._update_back_button()
    
    def _update_back_button(self) -> None:
        """Update back button enabled state."""
        can_go_back = self.web_view.history().canGoBack()
        self.back_button.setEnabled(can_go_back)
    
    def _navigate_to_url(self) -> None:
        """Navigate to the URL entered in the URL input box."""
        url_text = self.url_input.text().strip()
        if not url_text:
            return
        
        # Add https:// if no protocol specified
        if not url_text.startswith(("http://", "https://")):
            url_text = "https://" + url_text
        
        self.web_view.setUrl(QtCore.QUrl(url_text))
    
    def _navigate_back(self) -> None:
        """Navigate back in browser history."""
        if self.web_view.history().canGoBack():
            self.web_view.back()
            # Update button state after navigation
            QtCore.QTimer.singleShot(100, self._update_back_button)


class MainWindow(QtWidgets.QWidget):
    def __init__(self, settings: MateSettings, events: EventBus, state: RuntimeState, ctx=None) -> None:
        super().__init__()
        self.settings = settings
        self.events = events
        self.state = state
        self.ctx = ctx  # Store context reference for clean shutdown
        self.logger = get_logger("ui.shell")
        self._tabs: dict[int, TabContainer] = {}  # tab index -> tab container
        self._current_tab_index = 0
        self._current_view_mode = "chatgpt"  # "chatgpt" or "browser"
        self._chatgpt_view: ChatGPTView | None = None

        self._setup_window()
        self._build_layout()
        self._wire_events()
        self._apply_styles()
        # Install event filter to catch wheel events from child widgets
        self.installEventFilter(self)
        # Enable mouse tracking for cursor updates
        self.setMouseTracking(True)

    def _setup_window(self) -> None:
        self.setWindowTitle("mate — stealth companion")
        flags = QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.Tool
        if self.settings.ui.always_on_top:
            flags |= QtCore.Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(self.settings.ui.opacity)
        # Enable window resizing
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.resize(1100, 640)

    def _build_layout(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Stacked widget to switch between ChatGPT view and full browser view
        self.view_stack = QtWidgets.QStackedWidget()
        outer.addWidget(self.view_stack)

        # ChatGPT-only view (default)
        self._chatgpt_view = ChatGPTView(self, self.settings.web.start_url)
        self.view_stack.addWidget(self._chatgpt_view)

        # Full browser view
        self.overlay = QtWidgets.QFrame()
        self.overlay.setObjectName("Overlay")
        self.overlay.setMouseTracking(True)  # Enable mouse tracking for cursor updates
        overlay_layout = QtWidgets.QVBoxLayout(self.overlay)
        overlay_layout.setContentsMargins(8, 6, 8, 8)
        overlay_layout.setSpacing(6)

        self.title_bar = TitleBar("mate — stealth companion", self)
        self.title_bar.minimized.connect(self.showMinimized)
        self.title_bar.closed.connect(self.close)
        self.title_bar.toggled.connect(self._toggle_max_restore)
        self.title_bar.theme_toggled.connect(self._handle_theme_toggle)
        # Set initial theme state
        self.title_bar.set_theme(self.settings.ui.theme)
        overlay_layout.addWidget(self.title_bar)

        overlay_layout.addLayout(self._build_controls())
        overlay_layout.addWidget(self._build_splitter(), 1)
        overlay_layout.addWidget(self._build_status_strip())
        overlay_layout.addLayout(self._build_opacity_control())

        self.view_stack.addWidget(self.overlay)

        # Set ChatGPT view as default
        self.view_stack.setCurrentIndex(0)
        self._current_view_mode = "chatgpt"

    def _build_controls(self) -> QtWidgets.QLayout:
        # Empty layout - theme toggle moved to title bar
        layout = QtWidgets.QHBoxLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        # Empty controls - removed theme combo
        return layout
    
    def _build_opacity_control(self) -> QtWidgets.QLayout:
        """Build opacity control at the bottom of the window."""
        layout = QtWidgets.QHBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(6, 4, 6, 4)

        self.opacity_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(int(self.settings.ui.opacity * 100))
        self.opacity_slider.valueChanged.connect(self._handle_opacity_change)

        layout.addWidget(QtWidgets.QLabel("Opacity"))
        layout.addWidget(self.opacity_slider, 1)
        opacity_label = QtWidgets.QLabel(f"{int(self.settings.ui.opacity * 100)}%")
        opacity_label.setMinimumWidth(40)
        opacity_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.opacity_slider.valueChanged.connect(lambda v: opacity_label.setText(f"{v}%"))
        layout.addWidget(opacity_label)
        return layout

    def _build_splitter(self) -> QtWidgets.QSplitter:
        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Orientation.Horizontal)

        # Tab widget for multiple web pages
        self.tab_widget = QtWidgets.QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        
        # New tab button in tab bar corner (like Chrome)
        new_tab_button = QtWidgets.QPushButton("+")
        new_tab_button.setObjectName("NewTabButton")
        new_tab_button.setToolTip("New tab")
        new_tab_button.setFixedSize(24, 24)
        new_tab_button.clicked.connect(self._create_new_tab)
        self.tab_widget.setCornerWidget(new_tab_button, QtCore.Qt.Corner.TopRightCorner)
        
        # Create initial tab
        self._create_new_tab(self.settings.web.start_url)

        splitter.addWidget(self.tab_widget)
        return splitter

    def _build_status_strip(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QFrame()
        widget.setObjectName("StatusStrip")
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.status_label = QtWidgets.QLabel("Ready")
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        return widget

    def _wire_events(self) -> None:
        self.events.subscribe("snippet.used", self._on_snippet_used)
        if self.settings.privacy.prevent_capture:
            win32.prevent_capture(self, True)
        win32.set_taskbar_visibility(self, not self.settings.privacy.hide_from_taskbar)

    def _apply_styles(self) -> None:
        # Modern clean color scheme
        if self.settings.ui.theme == "dark":
            text = "#e5e7eb"
            bg_color = "#0a0a0f"
            surface = "#151520"
            surface_hover = "#1e1e2e"
            accent = "#6366f1"
            accent_hover = "#818cf8"
            border = "rgba(99, 102, 241, 0.2)"
            border_focus = "#6366f1"
        else:
            text = "#1f2937"
            bg_color = "#ffffff"
            surface = "#f8fafc"
            surface_hover = "#f1f5f9"
            accent = "#6366f1"
            accent_hover = "#818cf8"
            border = "rgba(99, 102, 241, 0.15)"
            border_focus = "#6366f1"

        # Apply styles to both browser overlay and ChatGPT view overlay
        stylesheet = f"""
            QWidget {{
                color: {text};
                font-family: 'Inter', 'Segoe UI', -apple-system, sans-serif;
                font-size: 13px;
            }}
            #Overlay {{
                background: {bg_color};
                border-radius: 4px;
                border: 2px solid {accent};
            }}
            #TitleBar {{
                background: transparent;
                border-radius: 0px;
                padding: 4px 8px;
            }}
            #TitleButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
                color: {text};
                padding: 2px 6px;
                font-weight: 500;
            }}
            #TitleButton:hover {{
                background: {surface_hover};
            }}
            #TitleButton:pressed {{
                background: {surface};
            }}
            #Toolbar {{
                background: transparent;
                border-radius: 12px;
                padding: 8px 12px;
            }}
            QSplitter::handle {{
                background: transparent;
                margin: 0px;
                width: 1px;
            }}
            QSplitter::handle:hover {{
                background: {border};
            }}
            #StatusStrip {{
                background: {surface};
                border-radius: 4px;
                border: none;
                padding: 4px 8px;
            }}
            QLabel#LevelLabel {{
                font-size: 11px;
                color: {text};
            }}
            QProgressBar#LevelBar {{
                background: {surface};
                border-radius: 6px;
                border: none;
                height: 8px;
            }}
            QProgressBar#LevelBar::chunk {{
                background: {accent};
                border-radius: 6px;
            }}
            QPushButton#PrimaryButton {{
                background: {accent};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: 600;
            }}
            QPushButton#PrimaryButton:hover {{
                background: {accent_hover};
            }}
            QPushButton#GhostButton {{
                background: {surface};
                color: {text};
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: 500;
            }}
            QPushButton#GhostButton:hover {{
                background: {surface_hover};
            }}
            #UrlBar {{
                background: {surface};
                border-radius: 4px;
                border: 1px solid {border};
                min-height: 32px;
                max-height: 32px;
            }}
            #NewTabButton {{
                background: {surface};
                color: {text};
                border: none;
                border-radius: 4px;
                padding: 4px;
                font-weight: 600;
                font-size: 16px;
                min-width: 24px;
                min-height: 24px;
            }}
            #NewTabButton:hover {{
                background: {surface_hover};
            }}
            QTabWidget::pane {{
                border: none;
                border-radius: 4px;
                background: transparent;
            }}
            QTabBar {{
                background: transparent;
                border: none;
            }}
            QTabBar::tab {{
                background: {surface};
                color: {text};
                border: none;
                padding: 6px 12px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-weight: 500;
            }}
            QTabBar::tab:selected {{
                background: {bg_color};
                color: {accent};
                border-bottom: 2px solid {accent};
            }}
            QTabBar::tab:hover:!selected {{
                background: {surface_hover};
            }}
            QTabBar::close-button {{
                image: none;
                subcontrol-origin: padding;
                subcontrol-position: right;
                width: 18px;
                height: 18px;
                background: transparent;
                border: none;
                border-radius: 6px;
            }}
            QTabBar::close-button:hover {{
                background: {surface_hover};
            }}
            QLineEdit {{
                background: {bg_color};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
                selection-background-color: {accent};
                selection-color: white;
            }}
            QLineEdit:focus {{
                border: 2px solid {border_focus};
                background: {bg_color};
            }}
            QPushButton#BackButton {{
                background: {surface};
                color: {text};
                border: none;
                border-radius: 4px;
                padding: 4px 8px;
                font-weight: 600;
                font-size: 14px;
            }}
            QPushButton#BackButton:hover {{
                background: {surface_hover};
            }}
            QPushButton#BackButton:disabled {{
                background: {surface};
                color: {text};
                opacity: 0.4;
            }}
            QPushButton#GoButton {{
                background: {accent};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
                font-weight: 600;
            }}
            QPushButton#GoButton:hover {{
                background: {accent_hover};
            }}
            QPushButton#ThemeSwitch {{
                background: {surface};
                color: {text};
                border: none;
                border-radius: 4px;
                padding: 4px;
                font-size: 14px;
            }}
            QPushButton#ThemeSwitch:checked {{
                background: {accent};
                color: white;
            }}
            QPushButton#ThemeSwitch:hover {{
                background: {surface_hover};
            }}
            QPushButton#ThemeSwitch:checked:hover {{
                background: {accent_hover};
            }}
            QComboBox {{
                background: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 4px 8px;
            }}
            QComboBox:hover {{
                background: {surface_hover};
                border: 1px solid {border_focus};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {text};
                margin-right: 8px;
            }}
            QSlider::groove:horizontal {{
                background: {surface};
                height: 6px;
                border-radius: 3px;
                border: none;
            }}
            QSlider::handle:horizontal {{
                background: {accent};
                border: none;
                width: 18px;
                height: 18px;
                border-radius: 9px;
                margin: -6px 0;
            }}
            QSlider::handle:horizontal:hover {{
                background: {accent_hover};
            }}
            QLabel {{
                color: {text};
            }}
            """
        
        # Apply styles to browser overlay
        self.overlay.setStyleSheet(stylesheet)
        
        # Apply styles to ChatGPT view overlay if it exists
        if self._chatgpt_view and hasattr(self._chatgpt_view, 'overlay'):
            self._chatgpt_view.overlay.setStyleSheet(stylesheet)

    def _on_snippet_used(self, snippet) -> None:
        self.status_label.setText(f"Expanded {snippet.trigger}")

    def _handle_opacity_change(self, value: int) -> None:
        self.setWindowOpacity(value / 100)

    @QtCore.Slot()
    def _increaseOpacitySafe(self) -> None:  # noqa: N802
        """Increase window opacity."""
        current_opacity = self.windowOpacity()
        new_opacity = min(1.0, current_opacity + 0.05)  # Increase by 5%
        self.setWindowOpacity(new_opacity)
        # Sync slider
        self.opacity_slider.setValue(int(new_opacity * 100))
        self.status_label.setText(f"Opacity: {int(new_opacity * 100)}%")

    @QtCore.Slot()
    def _decreaseOpacitySafe(self) -> None:  # noqa: N802
        """Decrease window opacity."""
        current_opacity = self.windowOpacity()
        new_opacity = max(0.2, current_opacity - 0.05)  # Decrease by 5%, minimum 20%
        self.setWindowOpacity(new_opacity)
        # Sync slider
        self.opacity_slider.setValue(int(new_opacity * 100))
        self.status_label.setText(f"Opacity: {int(new_opacity * 100)}%")

    def _handle_theme_change(self, theme: str) -> None:
        self.settings.ui.theme = theme
        self._apply_styles()
        # Update title bar theme states
        self.title_bar.set_theme(theme)
        if self._chatgpt_view and hasattr(self._chatgpt_view, 'title_bar'):
            self._chatgpt_view.title_bar.set_theme(theme)
    
    def _handle_theme_toggle(self) -> None:
        """Handle theme toggle from title bar button."""
        # Toggle theme
        new_theme = "dark" if self.settings.ui.theme == "light" else "light"
        self.settings.ui.theme = new_theme
        
        # Update title bar theme states
        self.title_bar.set_theme(new_theme)
        if self._chatgpt_view and hasattr(self._chatgpt_view, 'title_bar'):
            self._chatgpt_view.title_bar.set_theme(new_theme)
        
        # Apply new styles
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

    @QtCore.Slot()
    def _hideWindowSafe(self) -> None:  # noqa: N802
        """Hide the window (thread-safe)."""
        # Switch to ChatGPT view first, then hide after view change is complete
        if self._current_view_mode != "chatgpt":
            self._switch_to_chatgpt_view()
            # Process events to ensure view change is rendered before hiding
            QtWidgets.QApplication.processEvents()
        self.hide()

    @QtCore.Slot()
    def _showWindowSafe(self) -> None:  # noqa: N802
        """Show and activate the window (thread-safe)."""
        self.show()
        self.raise_()
        self.activateWindow()

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if self.settings.privacy.stealth_mode:
            win32.prevent_capture(self, True)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802
        """Handle window resize."""
        super().resizeEvent(event)

    def _get_resize_edge(self, pos: QtCore.QPoint) -> tuple[int, int]:
        """Determine which edge the mouse is near for resizing.
        Returns (horizontal_edge, vertical_edge) where:
        -1 = left/top, 0 = center, 1 = right/bottom
        """
        margin = 8
        rect = self.rect()
        x, y = pos.x(), pos.y()
        w, h = rect.width(), rect.height()
        
        h_edge = 0
        v_edge = 0
        
        if x < margin:
            h_edge = -1  # Left
        elif x >= w - margin:
            h_edge = 1  # Right
        
        if y < margin:
            v_edge = -1  # Top
        elif y >= h - margin:
            v_edge = 1  # Bottom
        
        return (h_edge, v_edge)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        """Handle mouse press for window resizing."""
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            h_edge, v_edge = self._get_resize_edge(event.position().toPoint())
            if h_edge != 0 or v_edge != 0:
                self._resize_edges = (h_edge, v_edge)
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geometry = self.geometry()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        """Handle mouse move for window resizing and cursor changes."""
        # Handle resizing if already in progress
        if hasattr(self, "_resize_edges") and self._resize_edges and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            h_edge, v_edge = self._resize_edges
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            new_geometry = QtCore.QRect(self._resize_start_geometry)
            
            if h_edge == -1:  # Left
                new_geometry.setLeft(new_geometry.left() + delta.x())
            elif h_edge == 1:  # Right
                new_geometry.setRight(new_geometry.right() + delta.x())
            
            if v_edge == -1:  # Top
                new_geometry.setTop(new_geometry.top() + delta.y())
            elif v_edge == 1:  # Bottom
                new_geometry.setBottom(new_geometry.bottom() + delta.y())
            
            # Enforce minimum size
            if new_geometry.width() >= 400 and new_geometry.height() >= 300:
                self.setGeometry(new_geometry)
            event.accept()
            return
        
        # Update cursor based on edge (only when not resizing)
        pos = event.position().toPoint()
        h_edge, v_edge = self._get_resize_edge(pos)
        
        # Update cursor based on edge
        if h_edge != 0 and v_edge != 0:
            # Corner
            if (h_edge == -1 and v_edge == -1) or (h_edge == 1 and v_edge == 1):
                self.setCursor(QtCore.Qt.CursorShape.SizeFDiagCursor)
            else:
                self.setCursor(QtCore.Qt.CursorShape.SizeBDiagCursor)
        elif h_edge != 0:
            self.setCursor(QtCore.Qt.CursorShape.SizeHorCursor)
        elif v_edge != 0:
            self.setCursor(QtCore.Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        """Handle mouse release after resizing."""
        if hasattr(self, "_resize_edges"):
            self._resize_edges = None
            self._resize_start_pos = None
            # Reset cursor after resizing
            self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)
    
    def leaveEvent(self, event: QtCore.QEvent) -> None:  # noqa: N802
        """Reset cursor when mouse leaves the window."""
        self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def _switch_to_chatgpt_view(self) -> None:
        """Switch to ChatGPT-only view."""
        if self._current_view_mode != "chatgpt":
            self.view_stack.setCurrentIndex(0)
            self._current_view_mode = "chatgpt"
            if self._chatgpt_view:
                QtCore.QTimer.singleShot(100, lambda: self._chatgpt_view.ensure_audio_enabled())
            self.logger.debug("Switched to ChatGPT view")
    
    def _switch_to_browser_view(self) -> None:
        """Switch to full browser view."""
        if self._current_view_mode != "browser":
            self.view_stack.setCurrentIndex(1)
            self._current_view_mode = "browser"
            self.logger.debug("Switched to browser view")
    
    @QtCore.Slot()
    def _toggleViewSafe(self) -> None:  # noqa: N802
        """Toggle between ChatGPT view and browser view."""
        if self._current_view_mode == "chatgpt":
            self._switch_to_browser_view()
        else:
            self._switch_to_chatgpt_view()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """Event filter to catch wheel events from child widgets and handle cursor updates."""
        # Disable opacity scroll in ChatGPT view
        if self._current_view_mode == "chatgpt" and event.type() == QtCore.QEvent.Type.Wheel:
            # Let the event pass through normally (no opacity control)
            return super().eventFilter(obj, event)
        
        # Handle cursor updates for child widgets
        if event.type() == QtCore.QEvent.Type.MouseMove and obj != self:
            # Convert child widget coordinates to main window coordinates
            if isinstance(obj, QtWidgets.QWidget):
                mouse_event = event
                if hasattr(mouse_event, 'position'):
                    child_pos = mouse_event.position().toPoint()
                else:
                    child_pos = mouse_event.pos()
                global_pos = obj.mapToGlobal(child_pos)
                window_pos = self.mapFromGlobal(global_pos)
                h_edge, v_edge = self._get_resize_edge(window_pos)
                
                # Update cursor based on edge
                if h_edge != 0 and v_edge != 0:
                    if (h_edge == -1 and v_edge == -1) or (h_edge == 1 and v_edge == 1):
                        self.setCursor(QtCore.Qt.CursorShape.SizeFDiagCursor)
                    else:
                        self.setCursor(QtCore.Qt.CursorShape.SizeBDiagCursor)
                elif h_edge != 0:
                    self.setCursor(QtCore.Qt.CursorShape.SizeHorCursor)
                elif v_edge != 0:
                    self.setCursor(QtCore.Qt.CursorShape.SizeVerCursor)
                else:
                    self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        
        if event.type() == QtCore.QEvent.Type.Wheel:
            wheel_event = event
            modifiers = wheel_event.modifiers()
            # Check if Ctrl+Shift is pressed
            if modifiers & QtCore.Qt.KeyboardModifier.ControlModifier and modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier:
                # Get current opacity
                current_opacity = self.windowOpacity()
                # Get scroll delta (positive = scroll up, negative = scroll down)
                delta = wheel_event.angleDelta().y()
                # Adjust opacity based on scroll direction (5% per scroll step)
                step = 0.05
                if delta > 0:
                    # Scroll up = increase opacity
                    new_opacity = min(1.0, current_opacity + step)
                else:
                    # Scroll down = decrease opacity (minimum 10% to keep window visible)
                    new_opacity = max(0.1, current_opacity - step)
                
                # Apply new opacity
                self.setWindowOpacity(new_opacity)
                # Sync slider
                self.opacity_slider.setValue(int(new_opacity * 100))
                # Update status label
                self.status_label.setText(f"Opacity: {int(new_opacity * 100)}%")
                # Update settings
                self.settings.ui.opacity = new_opacity
                # Return True to indicate we handled the event
                return True
        
        # Let other events pass through
        return super().eventFilter(obj, event)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: N802
        """Handle mouse wheel events to control opacity with Ctrl+Shift."""
        # Disable opacity scroll in ChatGPT view
        if self._current_view_mode == "chatgpt":
            super().wheelEvent(event)
            return
        
        modifiers = event.modifiers()
        # Check if Ctrl+Shift is pressed
        if modifiers & QtCore.Qt.KeyboardModifier.ControlModifier and modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier:
            # Get current opacity
            current_opacity = self.windowOpacity()
            # Get scroll delta (positive = scroll up, negative = scroll down)
            delta = event.angleDelta().y()
            # Adjust opacity based on scroll direction (5% per scroll step)
            step = 0.01
            if delta > 0:
                # Scroll up = increase opacity
                new_opacity = min(1.0, current_opacity + step)
            else:
                # Scroll down = decrease opacity (minimum 1% to keep window visible)
                new_opacity = max(0.05, current_opacity - step)
            
            # Apply new opacity
            self.setWindowOpacity(new_opacity)
            # Sync slider
            self.opacity_slider.setValue(int(new_opacity * 100))
            # Update status label
            self.status_label.setText(f"Opacity: {int(new_opacity * 100)}%")
            # Update settings
            self.settings.ui.opacity = new_opacity
            # Accept the event to prevent default handling
            event.accept()
            return
        
        # If not Ctrl+Shift, pass to parent for normal wheel handling
        super().wheelEvent(event)

    def _get_current_tab(self) -> TabContainer | None:
        """Get the currently active tab container."""
        current_index = self.tab_widget.currentIndex()
        return self._tabs.get(current_index)
    
    def _get_current_web_view(self) -> SilentWebView | None:
        """Get the currently active web view."""
        tab = self._get_current_tab()
        return tab.web_view if tab else None

    def _create_new_tab(self, url: str | None = None) -> None:
        """Create a new browser tab."""
        initial_url = url or self.settings.web.start_url
        tab_container = TabContainer(self, initial_url)
        
        # Add tab first to get the index
        tab_index = self.tab_widget.addTab(tab_container, "New Tab")
        self._tabs[tab_index] = tab_container
        
        web_view = tab_container.web_view
        
        # Set up page load handler
        page = web_view.page()
        if hasattr(page, "loadFinished"):
            def on_page_loaded(success: bool) -> None:
                self._on_page_loaded(web_view, success)
            page.loadFinished.connect(on_page_loaded)
        
        # Update tab title when page title changes
        def update_title(title: str) -> None:
            display_title = title[:30] + "..." if len(title) > 30 else title
            self.tab_widget.setTabText(tab_index, display_title or "New Tab")
        
        if hasattr(page, "titleChanged"):
            page.titleChanged.connect(update_title)
        
        # Navigate to initial URL
        web_view.setUrl(QtCore.QUrl(initial_url))
        
        # Ensure audio is enabled
        QtCore.QTimer.singleShot(100, lambda: self._ensure_audio_enabled(web_view))
        
        # Switch to new tab
        self.tab_widget.setCurrentIndex(tab_index)
        self._on_tab_changed(tab_index)
        
        self.logger.debug(f"Created new tab {tab_index} with URL: {initial_url}")

    def _close_tab(self, index: int) -> None:
        """Close a browser tab."""
        if self.tab_widget.count() <= 1:
            # Don't allow closing the last tab
            return
        
        tab_container = self._tabs.get(index)
        if tab_container:
            tab_container.deleteLater()
            del self._tabs[index]
        
        self.tab_widget.removeTab(index)
        
        # Update tab indices in _tabs dict
        new_tabs = {}
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if isinstance(widget, TabContainer):
                new_tabs[i] = widget
        self._tabs = new_tabs
        
        self.logger.debug(f"Closed tab {index}")

    def _on_tab_changed(self, index: int) -> None:
        """Handle tab change - sync state."""
        self._current_tab_index = index
        tab_container = self._tabs.get(index)
        if tab_container:
            web_view = tab_container.web_view
            # Ensure audio is enabled for the new tab
            QtCore.QTimer.singleShot(100, lambda wv=web_view: self._ensure_audio_enabled(wv))

    def _navigate_to_url(self) -> None:
        """Navigate to the URL entered in the URL input box."""
        # This method is no longer used - navigation is handled by TabContainer
        pass

    def _navigate_back(self) -> None:
        """Navigate back in browser history."""
        # This method is no longer used - navigation is handled by TabContainer
        pass

    def _on_url_changed(self, web_view: SilentWebView, url: QtCore.QUrl) -> None:
        """Handle URL changes from web view."""
        # Ensure audio stays enabled when URL changes
        QtCore.QTimer.singleShot(100, lambda wv=web_view: self._ensure_audio_enabled(wv))

    def _ensure_audio_enabled(self, web_view: SilentWebView | None = None) -> None:
        """Ensure web view audio is enabled and not muted."""
        if web_view is None:
            web_view = self._get_current_web_view()
        if not web_view:
            return
            
        page = web_view.page()
        if page:
            # Try setAudioMuted method first
            if hasattr(page, "setAudioMuted"):
                page.setAudioMuted(False)
            # Fallback to property
            elif hasattr(page, "audioMuted"):
                try:
                    page.audioMuted = False
                except (AttributeError, TypeError):
                    pass
            # Also try on the view itself
            if hasattr(web_view, "setAudioMuted"):
                web_view.setAudioMuted(False)
            elif hasattr(web_view, "audioMuted"):
                try:
                    web_view.audioMuted = False
                except (AttributeError, TypeError):
                    pass

    def _on_page_loaded(self, web_view: SilentWebView, success: bool) -> None:
        """Handle page load completion - ensure audio is enabled."""
        if success:
            self._ensure_audio_enabled(web_view)


    @QtCore.Slot()
    def _muteAudioSafe(self) -> None:  # noqa: N802
        """Mute audio for all tabs and ChatGPT view."""
        muted_count = 0
        
        # Mute ChatGPT view
        if self._chatgpt_view:
            web_view = self._chatgpt_view.web_view
            if web_view:
                page = web_view.page()
                if page:
                    if hasattr(page, "setAudioMuted"):
                        page.setAudioMuted(True)
                        muted_count += 1
                    elif hasattr(page, "audioMuted"):
                        try:
                            page.audioMuted = True
                            muted_count += 1
                        except (AttributeError, TypeError):
                            pass
        
        # Mute all browser tabs
        for tab_container in self._tabs.values():
            web_view = tab_container.web_view
            if not web_view:
                continue
                
            page = web_view.page()
            if page:
                if hasattr(page, "setAudioMuted"):
                    page.setAudioMuted(True)
                    muted_count += 1
                elif hasattr(page, "audioMuted"):
                    try:
                        page.audioMuted = True
                        muted_count += 1
                    except (AttributeError, TypeError):
                        pass
        
        if muted_count > 0:
            status_msg = f"Audio muted ({muted_count} view{'s' if muted_count != 1 else ''})"
            if hasattr(self, 'status_label'):
                self.status_label.setText(status_msg)
        else:
            if hasattr(self, 'status_label'):
                self.status_label.setText("Mute failed")

    @QtCore.Slot()
    def _unmuteAudioSafe(self) -> None:  # noqa: N802
        """Unmute audio for all tabs and ChatGPT view."""
        unmuted_count = 0
        
        # Unmute ChatGPT view
        if self._chatgpt_view:
            self._chatgpt_view.ensure_audio_enabled()
            unmuted_count += 1
        
        # Unmute all browser tabs
        for tab_container in self._tabs.values():
            web_view = tab_container.web_view
            if web_view:
                self._ensure_audio_enabled(web_view)
                unmuted_count += 1
        
        if unmuted_count > 0:
            status_msg = f"Audio unmuted ({unmuted_count} view{'s' if unmuted_count != 1 else ''})"
            if hasattr(self, 'status_label'):
                self.status_label.setText(status_msg)
        else:
            if hasattr(self, 'status_label'):
                self.status_label.setText("No views to unmute")

    @QtCore.Slot()
    def _panicQuitSafe(self) -> None:  # noqa: N802
        """Force full shutdown from any thread (hotkey-safe)."""
        # Stop context to clean up background threads and resources
        try:
            if self.ctx is not None and hasattr(self.ctx, "stop"):
                self.ctx.stop()
        except Exception:
            pass  # Ignore errors during shutdown
        
        # Close the window
        self.close()
        
        # Quit the application completely
        QtWidgets.QApplication.quit()
