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


class AudioSettings(BaseModel):
    mic_device: str | None = None
    speaker_device: str | None = None
    sample_rate: int = 16000
    frame_ms: int = Field(default=30, ge=10, le=120)
    block_size: int = 2048


class CaptionSettings(BaseModel):
    engine: Literal["placeholder", "whisper", "remote"] = "whisper"
    enable_speaker_detection: bool = True
    show_placeholder_captions: bool = False  # Only show real transcriptions by default
    mock_interval_ms: int = 1500
    whisper_executable: Path = Field(
        default_factory=lambda: Path("whisper.exe")
    )
    whisper_model_path: Path = Field(
        default_factory=lambda: Path.cwd() / "models" / "ggml-medium-q5_0.bin"  # Quantized medium model (best balance)
    )
    whisper_model_path_fast: Path = Field(
        default_factory=lambda: Path.cwd() / "models" / "ggml-tiny.bin"  # Tiny model for Layer A (fast)
    )
    whisper_device: str = "CABLE Output (VB-Audio Virtual Cable)"
    whisper_language: str = "en"
    whisper_prompt: str = ""  # Optional context prompt to guide transcription
    save_recordings: bool = False  # Save WAV files
    recordings_dir: Path = Field(
        default_factory=lambda: Path.cwd() / "recordings"
    )
    max_recordings: int = 1000  # Maximum number of recordings to keep (0 = unlimited)
    realtime_latency: float = 1.2  # Seconds to buffer before transcribing (lower = faster but less accurate)


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
        "toggle_engine",
        "panic_hide",
        "show_web",
        "mute_caption",
    ]
    payload: dict[str, Any] | None = None


class HotkeySettings(BaseModel):
    enabled: bool = True
    bindings: list[HotkeyBinding] = Field(
        default_factory=lambda: [
            HotkeyBinding(
                name="Toggle Overlay",
                shortcut="ctrl+shift+space",
                action="toggle_overlay",
            ),
            HotkeyBinding(
                name="Toggle Visibility",
                shortcut="ctrl+alt+m",
                action="toggle_visibility",
            ),
            HotkeyBinding(name="Panic Hide", shortcut="ctrl+shift+backspace", action="panic_hide"),
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
    audio: AudioSettings = Field(default_factory=AudioSettings)
    captions: CaptionSettings = Field(default_factory=CaptionSettings)
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

    if engine := os.getenv('MATE_CAPTION_ENGINE'):
        overrides.setdefault('captions', {})['engine'] = engine

    if whisper_exe := os.getenv('MATE_WHISPER_EXECUTABLE'):
        overrides.setdefault('captions', {})['whisper_executable'] = Path(whisper_exe)

    if model_path := os.getenv('MATE_WHISPER_MODEL'):
        overrides.setdefault('captions', {})['whisper_model_path'] = Path(model_path)
    
    if whisper_device := os.getenv('MATE_WHISPER_DEVICE'):
        overrides.setdefault('captions', {})['whisper_device'] = whisper_device

    settings = MateSettings(**overrides)
    settings.paths.ensure()
    return settings
