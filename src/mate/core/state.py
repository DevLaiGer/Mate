"""Runtime state containers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass(slots=True)
class CaptionFrame:
    """
    Represents a caption from speech recognition.
    
    Supports three-layer STT architecture:
    - Layer A: Quick partials (300ms) - low confidence, immediate feedback
    - Layer B: Medium windows (2-3s) - better confidence, overlapped processing
    - Layer C: Final pass - highest confidence, full utterance context
    """
    text: str
    speaker: str
    channel: Literal["mic", "speaker"]
    confidence: float
    is_partial: bool = False
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Enhanced timing for three-layer system
    start_time: float = field(default_factory=time.time)  # Audio start (seconds since epoch)
    end_time: float | None = None  # Audio end (None for ongoing partials)
    layer: Literal["A", "B", "C", "legacy"] = "legacy"  # Processing layer
    caption_id: str = ""  # Unique ID for tracking replacements
    
    @property
    def duration(self) -> float | None:
        """Get duration in seconds."""
        if self.end_time is None:
            return None
        return self.end_time - self.start_time


@dataclass(slots=True)
class RuntimeFlags:
    overlay_visible: bool = True
    caption_engine_active: bool = False
    snippet_engine_active: bool = False
    stealth_mode: bool = True


@dataclass(slots=True)
class RuntimeState:
    flags: RuntimeFlags = field(default_factory=RuntimeFlags)
    recent_captions: list[CaptionFrame] = field(default_factory=list)
    max_caption_history: int = 50

    def push_caption(self, frame: CaptionFrame) -> None:
        self.recent_captions.insert(0, frame)
        if len(self.recent_captions) > self.max_caption_history:
            self.recent_captions.pop()
