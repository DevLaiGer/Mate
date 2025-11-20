# Download Tiny Model for Fast Layer A

## Why You Need This

Layer A (fast partials) now uses **`ggml-tiny.bin`** instead of the slow medium model.

**Benefits**:
- ⚡ **20x faster** transcription for Layer A
- 📊 **75 MB** file size (vs 1.5 GB medium)
- 🎯 Captions appear in **~300ms** instead of 5-6s

---

## Download Command

### Windows PowerShell:
```powershell
Invoke-WebRequest -Uri "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin" -OutFile "models/ggml-tiny.bin"
```

### Alternative (curl):
```bash
curl -L "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin" -o "models/ggml-tiny.bin"
```

### Manual Download:
1. Go to: https://huggingface.co/ggerganov/whisper.cpp/tree/main
2. Download: `ggml-tiny.bin`
3. Place in: `models/ggml-tiny.bin`

---

## Verify Installation

```powershell
ls models/
```

**You should see**:
```
ggml-medium-q5_0.bin  (1.5 GB - for Layer B/C)
ggml-tiny.bin         (75 MB - for Layer A)
```

---

## Test It

Run your app:
```powershell
python -m mate
```

**Look for in logs**:
```
✓ Model (Layer B/C): ggml-medium-q5_0.bin (1500.0 MB)
✓ Model (Layer A): ggml-tiny.bin (75.0 MB)
```

✅ **Success!** Layer A will now be super fast!

---

## What If I Don't Download It?

The app will still work, but:
- ⚠️ Layer A will use medium model (slow)
- ⚠️ First captions will take 5-6s instead of 300ms
- ⚠️ You'll see this warning:
  ```
  ⚠ Fast model not found: models/ggml-tiny.bin, Layer A will use medium model (slower)
  ```

**Recommendation**: Download it for best experience! Only 75 MB.

