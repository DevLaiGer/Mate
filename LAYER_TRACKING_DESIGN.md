# Layer Tracking Design - Internal System

## How It Works Internally

The system tracks text from each layer and intelligently merges them:

### Internal State Tracking

```python
# Per channel (mic/speaker):
self._layer_a_text[channel] = ""  # Fast partial text from tiny model
self._layer_b_text[channel] = ""  # Confirmed accurate text from medium model
```

---

## Processing Flow

### Layer A (Fast Additions)
```python
# Layer A transcribes quickly with tiny model
text = "hello"
self._layer_a_text[channel] = "hello"

# Display: just Layer A text
display_text = "hello"
emit(display_text)  # User sees: "hello"
```

### Layer B (Confirmation + Merge)
```python
# Layer B transcribes with medium model (more accurate)
text = "hello world"
self._layer_b_text[channel] = "hello world"

# Get Layer A text
layer_a_text = "hello world this"  # Layer A got ahead!

# Merge logic:
# - Layer B confirmed: "hello world"
# - Layer A has more: "this"
# - Combine them!

if layer_a_text.startswith(layer_b_text):
    new_part = layer_a_text[len(layer_b_text):].strip()  # "this"
    display_text = layer_b_text + " " + new_part  # "hello world this"

emit(display_text)  # User sees: "hello world this"
```

### Layer C (Final)
```python
# Layer C transcribes full utterance (best accuracy)
text = "Hello world, this is a test."
display_text = text  # Final result, no merging needed

emit(display_text, is_partial=False)  # User sees final
```

---

## Example Timeline (Internal)

### Speech: "Hello world, this is a test"

#### T=0.3s - Layer A fires
```
Layer A transcribes: "hello"
_layer_a_text["mic"] = "hello"
Display: "hello"
```

#### T=0.6s - Layer A fires again
```
Layer A transcribes: "hello wo"
_layer_a_text["mic"] = "hello wo"
Display: "hello wo"
```

#### T=1.0s - Layer B fires (first time)
```
Layer B transcribes: "hello world"
_layer_b_text["mic"] = "hello world"
_layer_a_text["mic"] = "hello wo"  # Layer A is behind

Check merge:
- Layer B: "hello world" (11 chars)
- Layer A: "hello wo" (8 chars)
- Layer A is shorter, no merge needed

Display: "hello world"
```

#### T=1.3s - Layer A fires (gets ahead!)
```
Layer A transcribes: "hello world this"
_layer_a_text["mic"] = "hello world this"
Display: "hello world this"
```

#### T=1.5s - Layer B fires (catches up)
```
Layer B transcribes: "hello world this"
_layer_b_text["mic"] = "hello world this"
_layer_a_text["mic"] = "hello world this is"  # Layer A ahead again!

Check merge:
- Layer B: "hello world this" (16 chars)
- Layer A: "hello world this is" (19 chars)
- Layer A extends Layer B!

Extract new part:
new_part = "hello world this is"[16:].strip() = "is"

Display: "hello world this" + " " + "is" = "hello world this is"
```

#### T=2.0s - Layer A fires
```
Layer A transcribes: "hello world this is a"
_layer_a_text["mic"] = "hello world this is a"
Display: "hello world this is a"
```

#### T=2.5s - Layer B fires
```
Layer B transcribes: "hello world this is a test"
_layer_b_text["mic"] = "hello world this is a test"
_layer_a_text["mic"] = "hello world this is a"  # Layer A behind now

Check merge:
- Layer B: "hello world this is a test" (26 chars)
- Layer A: "hello world this is a" (21 chars)
- Layer B is longer, no merge needed

Display: "hello world this is a test"
```

#### T=5.4s - Layer C fires (FINAL)
```
Layer C transcribes: "Hello world, this is a test."
Display: "Hello world, this is a test."
is_partial = False (FINAL)

Clear state:
_layer_a_text["mic"] = ""
_layer_b_text["mic"] = ""
```

---

## Key Benefits

### 1. **Fast Feedback**
- Layer A shows text in ~300ms
- User sees *something* immediately

### 2. **Progressive Accuracy**
- Layer B confirms and corrects Layer A
- More accurate text replaces fast guesses

### 3. **Intelligent Merging**
- If Layer A gets ahead, we keep its additions
- Layer B confirms the base, Layer A adds new words
- Best of both worlds!

### 4. **Final Polish**
- Layer C provides best accuracy with full context
- Proper punctuation and capitalization

---

## Merge Logic Details

```python
# Pseudo-code for Layer B merging:

layer_b_confirmed = "hello world"
layer_a_fast = "hello world this is"

# Check if Layer A extends Layer B
if layer_a_fast.startswith(layer_b_confirmed):
    # Extract the new part Layer A discovered
    new_words = layer_a_fast[len(layer_b_confirmed):].strip()
    
    # Combine: confirmed base + new discoveries
    display_text = layer_b_confirmed + " " + new_words
    # Result: "hello world this is"
else:
    # Texts diverged, trust Layer B (more accurate)
    display_text = layer_b_confirmed
```

---

## Why This Works

### Problem Without Merging:
```
T=1.0s: Layer B shows "hello world"
T=1.3s: Layer A shows "hello world this"  ← User sees new word!
T=1.5s: Layer B shows "hello world this"  ← Jumps back, loses "is"!
```

### Solution With Merging:
```
T=1.0s: Layer B shows "hello world"
T=1.3s: Layer A shows "hello world this"
T=1.5s: Layer B confirms "hello world this" + Layer A has "is"
        → Display: "hello world this is"  ← Smooth progression!
```

---

## Edge Cases Handled

### Case 1: Layer A gets garbage
```
Layer A: "hello wor blah"  (tiny model error)
Layer B: "hello world"     (medium model correct)

Merge check: "hello wor blah" doesn't start with "hello world"
→ Display Layer B only: "hello world"
```

### Case 2: Layer B catches up completely
```
Layer A: "hello world"
Layer B: "hello world this is a test"

Layer B is longer → Display Layer B: "hello world this is a test"
```

### Case 3: Both layers aligned
```
Layer A: "hello world"
Layer B: "hello world"

No new part → Display: "hello world"
```

---

## Implementation Notes

### State Management
- `_layer_a_text`: Always stores latest Layer A result
- `_layer_b_text`: Always stores latest Layer B result
- Cleared on utterance end (Layer C finalization)

### Merging Strategy
- **Simple prefix check**: Does Layer A start with Layer B?
- **Length comparison**: Which has more text?
- **Conservative**: When in doubt, trust Layer B (more accurate)

### Performance
- Minimal overhead (just string comparison)
- No complex diff algorithms needed
- Works in real-time

---

## User Experience

From the user's perspective:

```
[Mic] hello                           ← Fast! (300ms)
[Mic] hello wo                        ← Updating...
[Mic] hello world                     ← Better!
[Mic] hello world this                ← Getting ahead...
[Mic] hello world this is             ← Merging layers!
[Mic] hello world this is a           ← Still going...
[Mic] hello world this is a test      ← Almost done...
[Mic] Hello world, this is a test.    ← FINAL! Perfect!
```

**One caption item, progressively refined!**

---

## Summary

✅ **Layer A**: Fast additions (tiny model)  
✅ **Layer B**: Confirmation + merge with Layer A's new words  
✅ **Layer C**: Final accurate result  
✅ **Smart merging**: Best of fast + accurate  
✅ **Smooth UX**: Progressive refinement, no jumps  

**Result**: User sees text appear quickly and improve over time!

