# Quick Start Guide - Whisper.cpp Setup

## Current Status

✅ **Code Migration Complete** - All Vosk code removed, Whisper integration ready  
❌ **Whisper.cpp Not Set Up** - You need to install whisper.cpp and download a model

The app is currently showing placeholder captions because Whisper.cpp is not yet configured.

## What You Need to Do

### Step 1: Create models directory

```powershell
mkdir models
```

### Step 2: Download Whisper.cpp

**Option A - Download Prebuilt (Easiest)**
1. Go to https://github.com/ggerganov/whisper.cpp/releases
2. Download the latest Windows release (look for `whisper-bin-x64.zip` or similar)
3. Extract `whisper.exe` (or `main.exe`) to your project root

**Option B - Build from Source**
```powershell
git clone https://github.com/ggerganov/whisper.cpp.git
cd whisper.cpp
cmake -S . -B build
cmake --build build --config Release
# Copy whisper.cpp/build/bin/Release/main.exe to project root as whisper.exe
```

### Step 3: Download a GGML Model

1. Visit https://huggingface.co/ggerganov/whisper.cpp/tree/main
2. Download one of these models:
   - **ggml-tiny.bin** (~75 MB) - Fastest, lowest quality
   - **ggml-small.bin** (~466 MB) - **RECOMMENDED** - Good balance
   - **ggml-medium.bin** (~1.5 GB) - Better quality, slower
3. Place the downloaded `.bin` file in the `models/` directory

### Step 4: Configure the App

Create a `.env` file in the project root:

```env
MATE_WHISPER_EXECUTABLE=whisper.exe
MATE_WHISPER_MODEL=models/ggml-small.bin
MATE_WHISPER_DEVICE="CABLE Output (VB-Audio Virtual Cable)"
MATE_CAPTION_ENGINE=whisper
```

### Step 5: Verify Setup

Run the verification script:

```powershell
python verify_whisper_setup.py
```

You should see: `[SUCCESS] ALL CHECKS PASSED!`

### Step 6: Run the App

```powershell
.\.venv\Scripts\Activate.ps1
poetry run mate
```

## What Changed

### ✅ Removed
- All Vosk imports and code
- Vosk model directories (deleted)
- Vosk dependency from pyproject.toml
- Placeholder captions when in whisper mode

### ✅ Added
- Whisper.cpp subprocess integration
- JSON and plain text output parsing
- Automatic whisper.exe detection
- Configuration for whisper settings
- Filter to show ONLY real transcriptions (no placeholders)

### Key Feature
**Now the app will ONLY show captions from actual microphone and speaker audio** - no more placeholder messages like "listening for voices" when in whisper mode.

## Expected Behavior

### Before Setup (Current)
- App shows placeholder messages every few seconds
- These are NOT real transcriptions

### After Setup
- App will be SILENT until it hears actual speech
- Only REAL transcriptions from mic/speaker will appear
- No placeholder messages will show

## Need Help?

### Whisper.cpp not starting?
- Check paths in `.env` file
- Verify whisper.exe exists and is executable
- Check model file is not corrupted
- Look at app logs for error messages

### No captions appearing?
- Ensure VB-Audio Cable is set up (see README.md)
- Check that audio is routing to CABLE Input
- Verify microphone "Listen to this device" is enabled
- Speak loudly or play audio to test

### Still seeing placeholders?
- Check `.env` has `MATE_CAPTION_ENGINE=whisper`
- Restart the app after configuration changes
- Run `python verify_whisper_setup.py` to check setup

## Direct Download Links

- **Whisper.cpp releases**: https://github.com/ggerganov/whisper.cpp/releases
- **GGML models**: https://huggingface.co/ggerganov/whisper.cpp/tree/main
- **VB-Audio Cable**: https://vb-audio.com/Cable/index.htm

## Next Steps After Setup

1. Test with speech - speak into your microphone
2. Test with system audio - play a YouTube video
3. Adjust model size if latency is too high or quality too low
4. Configure VB-Audio Cable routing for your specific needs

---

**Run the app now?** Make sure you complete Steps 1-4 first, then run:
```powershell
poetry run mate
```

The app will now show ONLY real captions from your mic and speaker! 🎉

