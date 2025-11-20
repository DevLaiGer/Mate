# ✅ Correct 3-Layer Transcription Method - Implementation

## What I Fixed

### ❌ **WRONG Approach (Before)**
- Layer A emits text
- Layer B tries to "merge" with Layer A
- Creates confusion and duplicates

### ✅ **CORRECT Approach (Now)**
- **Layer 1 (A)**: Emit temporary text → `is_partial=True`
- **Layer 2 (B)**: **REPLACE** Layer 1 completely → `is_partial=True`
- **Layer 3 (C)**: **REPLACE** everything with final → `is_partial=False`

---

## The 3-Layer Method (Correct Implementation)

### **Layer 1 – Fast Preview (200-400ms chunks)**

**Goal**: Show text instantly

```python
# Layer A transcribes with tiny model
text = "hello"

# Emit as temporary partial
emit(
    text="hello",
    is_partial=True,    # ← Temporary, will be replaced
    confidence=0.5,     # ← Low confidence
    layer="A"
)
```

**User sees**: `[Mic] hello …`

---

### **Layer 2 – Improved Preview (1-3s chunks)**

**Goal**: More accurate, **REPLACES** Layer 1

```python
# Layer B transcribes with medium model
text = "hello world"

# Emit as improved partial (REPLACES Layer 1)
emit(
    text="hello world",
    is_partial=True,    # ← Still replaceable by Layer 3
    confidence=0.75,    # ← Medium confidence
    layer="B"
)
```

**User sees**: `[Mic] hello world …` ← **REPLACED** "hello"

**Key**: Same `caption_id`, so UI updates the same item!

---

### **Layer 3 – Final Result (Full utterance after silence)**

**Goal**: Highest accuracy, **REPLACES** everything

```python
# Layer C transcribes full utterance
text = "Hello world, this is a test."

# Emit as FINAL (REPLACES Layer 1 and 2)
emit(
    text="Hello world, this is a test.",
    is_partial=False,   # ← FINAL, locked
    confidence=0.95,    # ← High confidence
    layer="C"
)
```

**User sees**: `[Mic] Hello world, this is a test.` ← **FINAL**

---

## How Replacement Works

### UI Logic (Already Correct in shell.py)

```python
# If is_partial=True:
if item exists for this channel:
    UPDATE same item  # ← Layer 2 replaces Layer 1
else:
    CREATE new item

# If is_partial=False:
if item exists for this channel:
    UPDATE to final style  # ← Layer 3 replaces Layer 2
else:
    CREATE new item
```

### Key: Same `caption_id` Per Utterance

```python
# When utterance starts:
self._active_caption_id[channel] = str(uuid.uuid4())

# All layers use SAME ID:
Layer A: caption_id = "abc123"
Layer B: caption_id = "abc123"  # ← Same ID = replaces Layer A
Layer C: caption_id = "abc123"  # ← Same ID = replaces Layer B
```

---

## Example Timeline

### Speech: "Hello world, this is a test"

```
T=0.3s  Layer 1: "hello"
        Display: [Mic] hello …
        (is_partial=True, layer=A)

T=0.6s  Layer 1: "hello wo"
        Display: [Mic] hello wo …
        (REPLACES previous Layer 1)

T=1.0s  Layer 2: "hello world"
        Display: [Mic] hello world …
        (REPLACES Layer 1, is_partial=True, layer=B)

T=1.5s  Layer 2: "hello world this"
        Display: [Mic] hello world this …
        (REPLACES previous Layer 2)

T=2.0s  Layer 2: "hello world this is"
        Display: [Mic] hello world this is …
        (REPLACES previous Layer 2)

T=2.5s  Layer 2: "hello world this is a test"
        Display: [Mic] hello world this is a test …
        (REPLACES previous Layer 2)

T=5.4s  Layer 3: "Hello world, this is a test."
        Display: [Mic] Hello world, this is a test.
        (REPLACES Layer 2, is_partial=False, layer=C, FINAL!)
```

**Result**: ONE caption item, progressively upgraded!

---

## Key Principles

### ✅ **1. Always Replace, Never Merge**
- Layer 2 **replaces** Layer 1 completely
- Layer 3 **replaces** Layer 2 completely
- No "merging" or "combining"

### ✅ **2. Same caption_id = Same UI Item**
- All layers use same `caption_id` for one utterance
- UI updates the same item, not creates new ones

### ✅ **3. Confidence Levels**
- Layer 1: 0.5 (low - temporary)
- Layer 2: 0.75 (medium - improved)
- Layer 3: 0.95 (high - final)

### ✅ **4. Partial vs Final**
- Layer 1, 2: `is_partial=True` (replaceable)
- Layer 3: `is_partial=False` (locked, final)

### ✅ **5. No Duplicates**
- Because we use same `caption_id` and `is_partial` flag
- UI knows to update, not create new

---

## What Changed in Code

### Before (WRONG):
```python
# Layer B tried to "merge" with Layer A
layer_a_text = self._layer_a_text[channel]
if layer_a_text has more:
    display_text = layer_b + " " + new_part  # ❌ WRONG!
```

### After (CORRECT):
```python
# Layer B simply replaces Layer A
display_text = text.strip()  # ✅ Just use Layer B text!

emit(
    text=display_text,
    is_partial=True,  # Will be replaced by Layer 3
    caption_id=self._active_caption_id[channel]  # Same ID
)
```

---

## Benefits

✅ **No duplicates** - same caption_id ensures replacement  
✅ **No repeated text** - each layer replaces previous  
✅ **Fast feedback** - Layer 1 appears in 300ms  
✅ **Progressive accuracy** - Layer 2 improves, Layer 3 finalizes  
✅ **Clean UX** - one caption item, smoothly upgraded  

---

## Summary

### The Golden Rule:
**"Later layers REPLACE earlier layers, never merge or duplicate."**

### Implementation:
1. **Layer 1**: Fast temporary text (`is_partial=True`)
2. **Layer 2**: Better text, **REPLACES** Layer 1 (`is_partial=True`)
3. **Layer 3**: Final text, **REPLACES** Layer 2 (`is_partial=False`)

### UI Behavior:
- Same `caption_id` → Updates same item
- `is_partial=True` → Shows "…" suffix
- `is_partial=False` → Removes "…", locks caption

**Result**: Perfect 3-layer transcription with no duplicates!

---

## Status

✅ **Corrected and ready to test!**

Download tiny model and test the proper replacement behavior!

