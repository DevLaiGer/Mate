# Architecture overview

Mate is intentionally modular so future features (live caption routing, automation plugins, stealth overlays) can evolve without rewriting the base. The current scaffolding is split into five layers:

1. **Configuration & logging** (`mate.config`, `mate.logging`)
   - Pydantic models encapsulate UI, audio, caption, snippet, hotkey, privacy, and web prefs.
   - `.env` overrides hydrate those models and paths are materialised inside `AppPaths`.
   - Loguru is configured once and shared via `get_logger`.

2. **Core runtime** (`mate.core`)
   - `EventBus` is a thread-safe pub/sub hub.
   - `RuntimeState` mirrors caption/flag changes for the UI.
   - `build_context` wires settings into services and exposes a `MateContext` facade with `start/stop` hooks.

3. **Audio & captions** (`mate.audio`)
   - `AudioCapture` is responsible for microphone frames via `sounddevice` and dispatches them to listeners.
   - `CaptionEngine` currently emits mock frames but already publishes to the event bus, so swapping in Whisper / WhisperX is isolated to this module.

4. **Automation services** (`mate.services`)
   - `SnippetEngine` tracks typed buffers and expands triggers.
   - `HotkeyManager` registers keyboard shortcuts and bridges them to higher-level callbacks and events.

5. **Presentation** (`mate.ui`)
   - `MainWindow` hosts the animated overlay, caption feed, web viewport, and controls (opacity/theme toggles).
   - `TitleBar` delivers window chrome, drag support, and minimize/maximize/close actions.
   - Win32 helpers enforce stealth policies (hide from taskbar, prevent capture).

Supporting utilities (`mate.utils.process`, `mate.utils.win32`) provide single-instance locks and native tweaks.

The `mate.main` entrypoint orchestrates the above: settings -> logging -> context -> Qt application -> UI -> service start. Typer-based CLI commands wrap the same bootstrap flow for convenience.
