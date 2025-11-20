# mate — stealth OS companion

Mate is a Windows-first companion app that combines a stealth caption overlay, web HUD, text expansion, and global hotkeys inside a single PySide6 shell. This repository ships a **realtime speech-to-text engine** powered by **whisper.cpp** designed for rapid iteration toward the full feature set (live captions from mic/speaker, stealth UI, automation hooks, etc.).

## Highlights

- **Modern UI shell** built with PySide6, frameless, rounded, animated-ready, and opacity-adjustable.
- **Realtime speech recognition** using whisper.cpp with VB-Audio Cable for mic + speaker capture.
- **Audio pipeline** (WASAPI loopback + sounddevice) emitting caption events via an internal bus.
- **Snippet expander + hotkeys** backed by `keyboard`, intended for future persistence layers.
- **Event-driven architecture** with a runtime state store and clear service boundaries.
- **Stealth affordances** (hide from taskbar, prevent capture, opacity controls) wired into the UI layer.
- **Typer CLI** for launching, inspecting settings, and running diagnostics.

## Getting started

### Prerequisites

1. **Install VB-Audio Cable** (for capturing mic + speaker audio):
   - Download from [VB-Audio](https://vb-audio.com/Cable/) (free)
   - Install as Administrator
   - Set `CABLE Input` as your default playback device (or route specific apps to it)
   - Enable "Listen to this device" on your microphone → playback to `CABLE Input`

2. **Install whisper.cpp**:
   - Download prebuilt binary from [whisper.cpp releases](https://github.com/ggerganov/whisper.cpp/releases)
   - Or build from source (requires CMake + Visual Studio Build Tools)
   - Place `whisper.exe` (or `main.exe`) in the project root or `whisper.cpp/build/bin/Release/`

3. **Download a Whisper model**:
   - Get a GGML model file (e.g., `ggml-small.bin` or `ggml-medium.bin`)
   - Place in `models/` directory
   - Smaller models (tiny/small) = lower latency, larger models (medium/large) = better accuracy

### Running the app

```powershell
# 1) Activate the virtualenv
.\.venv\Scripts\Activate.ps1

# 2) Install dependencies (if poetry.lock changes)
poetry install

# 3) Launch the app
poetry run mate
```

To run with the Typer CLI commands:

```powershell
poetry run mate-cli doctor
poetry run mate-cli settings ui
```

### Configuration

Set environment variables in `.env` file:

```env
MATE_WHISPER_EXECUTABLE=whisper.exe
MATE_WHISPER_MODEL=models/ggml-small.bin
MATE_WHISPER_DEVICE="CABLE Output (VB-Audio Virtual Cable)"
MATE_CAPTION_ENGINE=whisper
```

## Project structure

```
src/mate/
  config.py         # Pydantic settings and load helper
  logging.py        # loguru bootstrap
  core/             # app context, events, runtime state
  audio/            # capture + caption scaffolding
  services/         # snippet + hotkey managers
  ui/               # widgets and PySide shell
  utils/            # win32 + process helpers
```

## Tests

```powershell
poetry run pytest
```

## Next steps

- Improve speaker detection (distinguish between mic and speaker audio).
- Persist snippets, hotkeys, and layout profiles (SQLite + SQLAlchemy).
- Extend stealth automation (window control, multi-display awareness).
- Integrate actual automation actions (web browse micro-apps, plugin SDK).
- Add remote API fallback for cloud-based transcription.

## Troubleshooting

**No audio captured:**
- Verify `CABLE Output` shows activity in Sound Control Panel → Recording
- Ensure apps are routed to `CABLE Input` playback device
- Check mic "Listen to this device" is enabled and pointing to `CABLE Input`

**Whisper.cpp not found:**
- Check `MATE_WHISPER_EXECUTABLE` path in `.env`
- Verify the executable exists and is not corrupted
- Try using absolute path

**Poor transcription quality:**
- Use a larger model (medium/large instead of small/tiny)
- Reduce background noise
- Adjust VB-Audio Cable levels

**High latency:**
- Use smaller model (tiny/small)
- Reduce whisper.cpp buffer settings if supported
- Close unnecessary applications
