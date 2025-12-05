"""Application configuration models and helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field


class AppPaths(BaseModel):
    """Resolved directories for mate runtime assets."""

    base_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("MATE_HOME", Path.home() / ".mate"))
    )

    @property
    def config_dir(self) -> Path:
        return self.base_dir / "config"

    @property
    def logs_dir(self) -> Path:
        return self.base_dir / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.base_dir / "cache"

    @property
    def data_dir(self) -> Path:
        return self.base_dir / "data"

    def ensure(self) -> None:
        for path in (self.base_dir, self.config_dir, self.logs_dir, self.cache_dir, self.data_dir):
            path.mkdir(parents=True, exist_ok=True)


class UISettings(BaseModel):
    theme: Literal["light", "dark"] = "light"
    opacity: float = Field(default=0.5, ge=0.2, le=1.0)
    animation_ms: int = Field(default=320, ge=60, le=2000)
    border_radius: int = Field(default=24, ge=8, le=48)
    always_on_top: bool = True




class SnippetSettings(BaseModel):
    enabled: bool = True
    max_buffer: int = Field(default=120, ge=10, le=400)
    defaults: list[dict[str, str]] = Field(
        default_factory=lambda: [
            {"trigger": "//mate", "replacement": "Mate is alive"},
            {"trigger": "::sig", "replacement": "Best regards, Mate"},
        ]
    )


class HotkeyBinding(BaseModel):
    name: str
    shortcut: str
    action: Literal[
        "toggle_overlay",
        "toggle_visibility",
        "hide_window",
        "show_window",
        "toggle_engine",
        "panic_hide",
        "show_web",
        "mute_audio",
        "unmute_audio",
        "increase_opacity",
        "decrease_opacity",
        "toggle_view",
    ]
    payload: dict[str, Any] | None = None


class HotkeySettings(BaseModel):
    enabled: bool = True
    bindings: list[HotkeyBinding] = Field(
        default_factory=lambda: [
            HotkeyBinding(
                name="Hide Window",
                shortcut="ctrl+shift+z",
                action="hide_window",
            ),
            HotkeyBinding(
                name="Show Window",
                shortcut="ctrl+shift+b",
                action="show_window",
            ),
            HotkeyBinding(name="Panic Hide", shortcut="alt+z", action="panic_hide"),
            HotkeyBinding(name="Mute Audio", shortcut="alt+x", action="mute_audio"),
            HotkeyBinding(name="Unmute Audio", shortcut="alt+b", action="unmute_audio"),
            HotkeyBinding(
                name="Increase Opacity",
                shortcut="ctrl+shift+up",
                action="increase_opacity",
            ),
            HotkeyBinding(
                name="Decrease Opacity",
                shortcut="ctrl+shift+down",
                action="decrease_opacity",
            ),
            HotkeyBinding(
                name="Toggle View",
                shortcut="ctrl+shift+f8",
                action="toggle_view",
            ),
        ]
    )


class PrivacySettings(BaseModel):
    prevent_capture: bool = True
    hide_from_taskbar: bool = True
    stealth_mode: bool = True


class WebSettings(BaseModel):
    start_url: str = "https://www.chatgpt.com"
    allow_navigation: bool = True


class MateSettings(BaseModel):
    app_name: str = "mate"
    paths: AppPaths = Field(default_factory=AppPaths)
    ui: UISettings = Field(default_factory=UISettings)
    snippets: SnippetSettings = Field(default_factory=SnippetSettings)
    hotkeys: HotkeySettings = Field(default_factory=HotkeySettings)
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)
    web: WebSettings = Field(default_factory=WebSettings)


def _maybe_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _maybe_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return None


def load_settings(env_path: Path | None = None) -> MateSettings:
    """Load user settings from environment variables and defaults."""

    env_file = env_path or Path('.env')
    if env_file.exists():
        load_dotenv(env_file)

    overrides: dict[str, Any] = {}

    if theme := os.getenv('MATE_THEME'):
        overrides.setdefault('ui', {})['theme'] = theme.lower()

    if opacity := _maybe_float(os.getenv('MATE_OPACITY')):
        overrides.setdefault('ui', {})['opacity'] = opacity

    if (always_on_top := _maybe_bool(os.getenv('MATE_ALWAYS_ON_TOP'))) is not None:
        overrides.setdefault('ui', {})['always_on_top'] = always_on_top

    if (stealth := _maybe_bool(os.getenv('MATE_STEALTH'))) is not None:
        overrides.setdefault('privacy', {})['stealth_mode'] = stealth

    if start_url := os.getenv('MATE_START_URL'):
        overrides.setdefault('web', {})['start_url'] = start_url


    settings = MateSettings(**overrides)
    settings.paths.ensure()
    return settings
