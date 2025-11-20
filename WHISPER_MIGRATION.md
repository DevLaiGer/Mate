# Whisper Migration Summary

## Overview

Successfully removed all Vosk-based speech recognition code and replaced it with a Whisper.cpp-based implementation. The new system uses subprocess to run whisper.cpp for realtime transcription of audio from both microphone and speaker (via VB-Audio Cable).

## Changes Made

### 1. Configuration (`src/mate/config.py`)

**Removed:**
- `vosk_model_path` setting
- Vosk engine option from `engine` literal type

**Added:**
- `whisper_executable`: Path to whisper.cpp executable (default: `whisper.exe`)
- `whisper_model_path`: Path to GGML model file (default: `models/ggml-small.bin`)
- `whisper_device`: Audio device for capture (default: `"CABLE Output (VB-Audio Virtual Cable)"`)
- `whisper_language`: Language code for transcription (default: `"en"`)

**Environment Variables:**
- `MATE_WHISPER_EXECUTABLE` - Path to whisper executable
- `MATE_WHISPER_MODEL` - Path to GGML model
- `MATE_WHISPER_DEVICE` - Audio device name

### 2. Caption Engine (`src/mate/audio/caption_engine.py`)

**Complete Rewrite:**
- Removed all Vosk imports (`vosk.Model`, `vosk.KaldiRecognizer`)
- Removed Vosk-specific code (`_start_vosk_pipeline`, `_recognize_loop`, etc.)
- Implemented subprocess-based whisper.cpp integration:
  - `_start_whisper_pipeline()`: Launches whisper.cpp as subprocess
  - `_stop_whisper_pipeline()`: Terminates whisper subprocess gracefully
  - `_whisper_reader_loop()`: Reads stdout from whisper.cpp
  - `_process_whisper_json()`: Parses JSON output from whisper
  - `_process_whisper_text()`: Handles plain text output fallback

**Key Features:**
- Automatic detection of whisper executable in multiple locations
- JSON and plain text output parsing
- Graceful fallback to placeholder captions on failure
- Proper subprocess cleanup on stop

### 3. Dependencies (`pyproject.toml`)

**Removed:**
- `vosk (>=0.3.45,<0.4.0)` dependency

The application no longer requires the vosk package, reducing dependencies.

### 4. Model Files

**Deleted:**
- `vosk-model-en-us-0.42-gigaspeech/` directory
- `vosk-model-small-en-us-0.15/` directory
- `vosk-model-en-us-0.42-gigaspeech.zip`
- `vosk-model-small-en-us-0.15.zip`

### 5. Documentation (`README.md`)

**Updated:**
- Added Prerequisites section with VB-Audio Cable setup instructions
- Added whisper.cpp installation instructions
- Added model download instructions
- Added Configuration section with environment variables
- Added Troubleshooting section
- Updated highlights to mention whisper.cpp and VB-Audio Cable

## Architecture Changes

### Before (Vosk)
```
Audio Capture → PCM16 Conversion → Vosk KaldiRecognizer → JSON Result → Caption Frame
```

### After (Whisper.cpp)
```
VB-Audio Cable → whisper.cpp subprocess → JSON/Text Output → Caption Frame
```

## Key Differences

| Aspect | Vosk | Whisper.cpp |
|--------|------|-------------|
| Integration | Python library | External subprocess |
| Audio Input | Direct audio frames | Virtual audio device |
| Output Format | JSON via Python API | JSON/Text via stdout |
| Model Format | Vosk models | GGML models |
| Setup Complexity | Simple (pip install) | Requires separate installation |
| Quality | Good | Excellent (state-of-the-art) |
| Latency | Low | Medium (model-dependent) |

## Setup Instructions for Users

### 1. Install VB-Audio Cable

1. Download from https://vb-audio.com/Cable/ (free)
2. Run installer as Administrator
3. In Windows Sound Settings:
   - Set `CABLE Input (VB-Audio Virtual Cable)` as default playback device
   - Or route specific apps to it via App volume settings
4. In Sound Control Panel → Recording tab:
   - Right-click your microphone → Properties
   - Go to Listen tab
   - Check "Listen to this device"
   - Select "CABLE Input (VB-Audio Virtual Cable)" as playback device
   - Apply

### 2. Install whisper.cpp

**Option A: Download Prebuilt Binary**
1. Visit https://github.com/ggerganov/whisper.cpp/releases
2. Download the latest Windows release
3. Extract `whisper.exe` (or `main.exe`) to project root

**Option B: Build from Source**
```powershell
git clone https://github.com/ggerganov/whisper.cpp.git
cd whisper.cpp
cmake -S . -B build
cmake --build build --config Release
```
The executable will be in `build/bin/Release/`

### 3. Download Whisper Model

1. Download a GGML model from whisper.cpp releases or convert from OpenAI Whisper
2. Recommended models:
   - `ggml-tiny.bin` - Fastest, lowest quality (~75 MB)
   - `ggml-small.bin` - Good balance (~466 MB)
   - `ggml-medium.bin` - Better quality, slower (~1.5 GB)
3. Place in `models/` directory

### 4. Configure Application

Create or update `.env` file:
```env
MATE_WHISPER_EXECUTABLE=whisper.exe
MATE_WHISPER_MODEL=models/ggml-small.bin
MATE_WHISPER_DEVICE="CABLE Output (VB-Audio Virtual Cable)"
MATE_CAPTION_ENGINE=whisper
```

### 5. Run the Application

```powershell
.\.venv\Scripts\Activate.ps1
poetry install
poetry run mate
```

## Troubleshooting

### No Audio Captured
- Open Sound Control Panel → Recording
- Select "CABLE Output" and click Properties
- Ensure it's enabled and set as default
- Speak/play audio and verify the green level meter moves

### Whisper Executable Not Found
- Verify the path in `.env` or use absolute path
- Check the executable exists and is not corrupted
- Try running whisper.exe manually to test

### Poor Transcription Quality
- Use a larger model (medium or large)
- Reduce background noise
- Adjust microphone levels in Windows
- Ensure audio is being routed correctly to CABLE

### High Latency
- Use smaller model (tiny or small)
- Close unnecessary applications
- Consider upgrading CPU (whisper.cpp is CPU-intensive)

### Echo/Feedback
- Disable "Listen to this device" when not using the app
- Use headphones instead of speakers
- Or use VoiceMeeter Banana for more advanced routing

## Future Improvements

1. **Speaker Detection**: Distinguish between mic and speaker audio (currently labeled as "Mixed")
2. **GPU Acceleration**: Add support for whisper.cpp with CUDA/CoreML/Metal backends
3. **Model Management**: Auto-download and manage models within the app
4. **VAD Integration**: Add Voice Activity Detection to reduce processing of silence
5. **Fine-tuned Models**: Support custom or domain-specific Whisper models
6. **Streaming API**: Add option for cloud-based transcription (OpenAI Whisper API)

## Testing Checklist

- [ ] VB-Audio Cable installed and configured
- [ ] whisper.cpp executable present and working
- [ ] GGML model downloaded and accessible
- [ ] `.env` file configured with correct paths
- [ ] Application starts without errors
- [ ] Audio levels visible in UI for mic and speaker
- [ ] Captions appear when speaking
- [ ] Captions appear for system audio (e.g., YouTube video)
- [ ] Fallback to placeholder captions works if whisper fails

## Notes

- The default engine is now `whisper` instead of `vosk`
- If whisper.cpp is not set up, the app will fall back to placeholder captions
- The implementation is flexible and can work with different whisper.cpp versions
- JSON parsing handles multiple possible output formats from whisper.cpp
- Plain text fallback ensures compatibility even if JSON output is not supported

## Migration Complete ✓

All Vosk-based code has been successfully removed and replaced with Whisper.cpp integration. The application is now ready to use state-of-the-art speech recognition with the flexibility to capture both microphone and speaker audio.

