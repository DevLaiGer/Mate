# ✅ Fixed: RealtimeSTT Model Parameter Error

## Error Explained

```
ValueError: Invalid model size 'en', expected one of: 
tiny.en, tiny, base.en, base, small.en, small, medium.en, medium, 
large-v1, large-v2, large-v3, large, distil-large-v2, distil-medium.en, 
distil-small.en, distil-large-v3, large-v3-turbo, turbo
```

### Problem:
I was passing `"en"` (language code) as the **model** parameter, but RealtimeSTT expects a **model size**.

### Fixed:
```python
# BEFORE (WRONG):
AudioToTextRecorder(
    model=self.settings.whisper_language,  # ❌ "en" is a language, not a model size
    language=self.settings.whisper_language,
)

# AFTER (CORRECT):
AudioToTextRecorder(
    model="base",  # ✅ Model size: tiny, base, small, medium, large
    language=self.settings.whisper_language,  # ✅ Language: en, es, fr, etc.
)
```

---

## Model Selection

### Available Models (fastest → slowest, least → most accurate):

| Model | Speed | Accuracy | Size | Best For |
|-------|-------|----------|------|----------|
| **tiny** | ⚡⚡⚡⚡⚡ | ⭐⭐ | ~75 MB | Ultra-fast, basic accuracy |
| **base** | ⚡⚡⚡⚡ | ⭐⭐⭐ | ~150 MB | **Good balance** ✅ |
| **small** | ⚡⚡⚡ | ⭐⭐⭐⭐ | ~500 MB | Better accuracy |
| **medium** | ⚡⚡ | ⭐⭐⭐⭐⭐ | ~1.5 GB | High accuracy |
| **large** | ⚡ | ⭐⭐⭐⭐⭐ | ~3 GB | Best accuracy, slow |

### Current Setting:
```python
model="base"  # Good balance of speed and accuracy
```

---

## How to Change Model

Edit `src/mate/audio/realtime_stt_processor.py`:

### For Faster (Less Accurate):
```python
AudioToTextRecorder(
    model="tiny",  # Fastest, basic accuracy
    ...
)
```

### For Better Accuracy (Slower):
```python
AudioToTextRecorder(
    model="small",  # Better accuracy, still reasonably fast
    ...
)
```

### For Best Accuracy (Slow):
```python
AudioToTextRecorder(
    model="medium",  # High accuracy, slower
    ...
)
```

---

## Model Download

RealtimeSTT **automatically downloads** the model on first run:
- Models are cached in `~/.cache/huggingface/`
- No manual download needed!
- First run will take longer (downloading model)

---

## Status

✅ **Error fixed**  
✅ **Using "base" model** (good balance)  
✅ **Ready to test**  

---

## Test Now

```bash
python -m mate
```

**First run**: Will download the "base" model (~150 MB)  
**After that**: Should work smoothly!

---

## Recommended Settings

### Default (Balanced):
```python
model="base"                        # Good speed + accuracy
post_speech_silence_duration=0.4    # 400ms to finalize
min_length_of_recording=0.5         # 500ms minimum
```

### For Speed:
```python
model="tiny"                        # Fastest
post_speech_silence_duration=0.2    # Finalize quickly
min_length_of_recording=0.3         # Shorter minimum
```

### For Accuracy:
```python
model="small"                       # More accurate
post_speech_silence_duration=0.6    # Wait longer
min_length_of_recording=0.8         # Longer minimum
```

---

**Issue resolved!** Run the app and RealtimeSTT will auto-download the "base" model.

