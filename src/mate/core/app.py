"""Mate application composition root."""

from __future__ import annotations

from dataclasses import dataclass

from mate.audio.caption_engine import CaptionEngine
from mate.audio.capture import AudioCapture
from mate.config import MateSettings
from mate.core.events import EventBus
from mate.core.state import RuntimeState
from mate.logging import get_logger
from mate.services.hotkeys import HotkeyManager
from mate.services.snippet_engine import SnippetEngine


@dataclass(slots=True)
class MateContext:
    settings: MateSettings
    events: EventBus
    state: RuntimeState
    caption_engine: CaptionEngine
    snippet_engine: SnippetEngine
    hotkeys: HotkeyManager

    def start(self) -> None:
        self.caption_engine.start()
        self.snippet_engine.start()
        self.hotkeys.start()

    def stop(self) -> None:
        self.caption_engine.stop()
        self.snippet_engine.stop()
        self.hotkeys.stop()


def build_context(settings: MateSettings) -> MateContext:
    events = EventBus()
    state = RuntimeState()
    audio_capture = AudioCapture(settings.audio)
    caption_engine = CaptionEngine(settings.captions, audio_capture, events)
    snippet_engine = SnippetEngine(settings.snippets, events)
    hotkeys = HotkeyManager(settings.hotkeys, events)

    logger = get_logger("bootstrap")
    logger.info("Mate context ready")

    return MateContext(
        settings=settings,
        events=events,
        state=state,
        caption_engine=caption_engine,
        snippet_engine=snippet_engine,
        hotkeys=hotkeys,
    )
