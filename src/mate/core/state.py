"""Runtime state containers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RuntimeFlags:
    overlay_visible: bool = True
    snippet_engine_active: bool = False
    stealth_mode: bool = True


@dataclass(slots=True)
class RuntimeState:
    flags: RuntimeFlags = field(default_factory=RuntimeFlags)
