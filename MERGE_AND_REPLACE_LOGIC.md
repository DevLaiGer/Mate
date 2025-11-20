# ✅ Merge & Replace Logic - Correct Implementation

## The Pattern You Showed

```
1. AAA...              (Layer A accumulates)
2. BBBAA...            (Layer B replaces A's confirmed part, keeps A's new part)
3. BBBBBAAAAA...       (Layer B grows, Layer A adds more ahead)
4. CCCCCCCCCC          (Layer C replaces everything - FINAL)

--- New utterance ---

5. AA...               (Layer A starts fresh)
6. BBAAAA...           (Layer B replaces A's confirmed, keeps A's new)
7. BBBBBBAA...         (Layer B grows, Layer A adds more)
8. CCCCCCCC            (Layer C replaces all - FINAL)
```

## The Rules

### ✅ **Within Same Layer: MERGE (Accumulate)**
- Layer A + Layer A → Merge/extend
- Layer B + Layer B → Merge/extend

### ✅ **Between Layers: REPLACE + APPEND**
- Layer B **replaces** confirmed part of Layer A
- Layer B **appends** new part from Layer A (if A got ahead)
- Layer C **replaces** everything

---

## Implementation Logic

### **Layer A (Fast Accumulation)**

```python
# First Layer A call:
Layer A transcribes: "hello"
_layer_a_accumulated = "hello"
Display: "hello"

# Second Layer A call:
Layer A transcribes: "hello world"
Check: Does "hello world" start with "hello"? YES
→ Extension, use new: "hello world"
_layer_a_accumulated = "hello world"
Display: "hello world"

# Third Layer A call:
Layer A transcribes: "hello world this"
Check: Does "hello world this" start with "hello world"? YES
→ Extension, use new: "hello world this"
_layer_a_accumulated = "hello world this"
Display: "hello world this"
```

**Pattern**: `AAA...` → `AAAA...` → `AAAAAA...`

---

### **Layer B (Replace Confirmed + Keep New)**

```python
# First Layer B call (Layer A has "hello world this"):
Layer B transcribes: "hello world"
_layer_b_accumulated = "hello world"
_layer_a_accumulated = "hello world this"

Check: Does Layer A have more? YES ("this")
→ Append Layer A's new part
Display: "hello world" + " this" = "hello world this"
```

**Pattern**: `BBBAA...` (B confirmed, A new)

```python
# Second Layer B call:
Layer B transcribes: "hello world this is"
_layer_b_accumulated = "hello world this is"
_layer_a_accumulated = "hello world this is a test"

Check: Does Layer A have more? YES ("a test")
→ Append Layer A's new part
Display: "hello world this is" + " a test" = "hello world this is a test"
```

**Pattern**: `BBBBBAAAAA...` (B confirmed more, A still ahead)

```python
# Third Layer B call:
Layer B transcribes: "hello world this is a test"
_layer_b_accumulated = "hello world this is a test"
_layer_a_accumulated = "hello world this is a test"

Check: Does Layer A have more? NO
→ Just show Layer B
Display: "hello world this is a test"
```

**Pattern**: `BBBBBBBBBB...` (B caught up)

---

### **Layer C (Final Replace)**

```python
# Layer C call (after silence):
Layer C transcribes: "Hello world, this is a test."
Display: "Hello world, this is a test."
is_partial = False (FINAL)

Clear all:
_layer_a_accumulated = ""
_layer_b_accumulated = ""
```

**Pattern**: `CCCCCCCCCC` (Final, replaces all)

---

## Complete Example Timeline

### Speech: "Hello world, this is a test"

```
T=0.3s  Layer A: "hello"
        _layer_a_accumulated = "hello"
        Display: "hello"
        Pattern: AAA

T=0.6s  Layer A: "hello wo"
        _layer_a_accumulated = "hello wo"
        Display: "hello wo"
        Pattern: AAAA (merged within A)

T=0.9s  Layer A: "hello world"
        _layer_a_accumulated = "hello world"
        Display: "hello world"
        Pattern: AAAAAA (merged within A)

T=1.0s  Layer B: "hello world"
        _layer_b_accumulated = "hello world"
        _layer_a_accumulated = "hello world"
        Display: "hello world"
        Pattern: BBBBBB (B replaces A, no new A)

T=1.3s  Layer A: "hello world this"
        _layer_a_accumulated = "hello world this"
        Display: "hello world this"
        Pattern: AAAAAAA (A adds more)

T=1.5s  Layer B: "hello world this"
        _layer_b_accumulated = "hello world this"
        _layer_a_accumulated = "hello world this is"
        Display: "hello world this" + " is" = "hello world this is"
        Pattern: BBBBBBBBBAA (B confirmed, A ahead)

T=2.0s  Layer A: "hello world this is a"
        _layer_a_accumulated = "hello world this is a"
        Display: "hello world this is a"
        Pattern: AAAAAAAAAAA (A adds more)

T=2.5s  Layer B: "hello world this is a test"
        _layer_b_accumulated = "hello world this is a test"
        _layer_a_accumulated = "hello world this is a"
        Display: "hello world this is a test"
        Pattern: BBBBBBBBBBBBBBBB (B caught up)

T=5.4s  Layer C: "Hello world, this is a test."
        Display: "Hello world, this is a test."
        Pattern: CCCCCCCCCCCCCC (FINAL)
```

---

## Code Logic

### Layer A Merging:
```python
if self._current_layer[channel] == "A":
    # Same layer - merge
    old_text = self._layer_a_accumulated[channel]
    if new_text.startswith(old_text):
        # Extension
        self._layer_a_accumulated[channel] = new_text
    else:
        # Different - append
        self._layer_a_accumulated[channel] = old_text + " " + new_text
```

### Layer B Replace + Append:
```python
if self._current_layer[channel] == "B":
    # Merge within Layer B
    self._layer_b_accumulated[channel] = merge(old_b, new_b)
    
    # Append new Layer A text
    if layer_a has more:
        self._layer_b_accumulated[channel] += " " + a_new_part
else:
    # First Layer B - replace Layer A
    self._layer_b_accumulated[channel] = new_text
    
    # Append Layer A's new part
    if layer_a has more:
        self._layer_b_accumulated[channel] += " " + a_new_part
```

### Layer C Replace All:
```python
# Layer C just replaces everything
display_text = layer_c_text
is_partial = False  # FINAL
```

---

## Visual Patterns

### Pattern 1: Layer A Accumulating
```
A     →  AA    →  AAA    →  AAAA
"h"      "he"     "hel"     "hello"
```

### Pattern 2: Layer B Replaces + Layer A Adds
```
AAAA      →  BBAA      →  BBBAA     →  BBBBAA
"hello"      "hel" + "lo"  "hello" + "wo"  "hello w" + "o"
(A only)     (B conf, A new) (B more, A ahead) (B more, A ahead)
```

### Pattern 3: Layer B Catches Up
```
BBBBAA    →  BBBBBB
"hello w" + "o"  "hello wo"
(B + A)          (B caught up)
```

### Pattern 4: Layer C Final
```
BBBBBB    →  CCCCCC
"hello wo"    "Hello world."
(B partial)   (C FINAL)
```

---

## Benefits

✅ **Fast feedback**: Layer A shows text immediately  
✅ **Continuous updates**: Layer A accumulates as you speak  
✅ **Progressive accuracy**: Layer B confirms and corrects  
✅ **Smart merging**: Layer B keeps Layer A's new discoveries  
✅ **Final polish**: Layer C provides best accuracy  
✅ **One caption**: All updates same item via `caption_id`  

---

## Summary

### The Golden Rules:

1. **Within same layer**: MERGE (accumulate/extend)
2. **Layer B replaces Layer A**: But keeps A's new part
3. **Layer C replaces all**: Final, no merging

### Display Pattern:
```
AAA... → AAAA... → BBBAA... → BBBBBAAAAA... → CCCCCCCCCC
```

**Result**: Smooth progression from fast → accurate → final!

---

## Status

✅ **Correctly implemented with merge + replace logic!**

Now Layer A accumulates, Layer B replaces + appends, Layer C finalizes!

