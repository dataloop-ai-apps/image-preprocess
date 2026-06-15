
# Plan: ETL Failure Info

> **Date**: 2025-06-12
> **Scope**: Add `etl` failure tracking to `item.metadata.system`, matching Rubiks behavior.

---

## 1. What Rubiks Does

Rubiks stores an `etl` object in `item.metadata.system.etl`:

```json
{ "etl": { "failed": true, "errors": ["msg1", "msg2"] } }
```

Both `failed` and `errors` are optional — present only when relevant.

**Scenarios (from Rubiks `imageProcessor.ts` + tests):**

| Scenario | `etl.failed` | `etl.errors` |
|---|---|---|
| Unsupported mimetype | `true` | _(absent)_ |
| EXIF parse error (exifr throws) | _(absent)_ | error appended — soft |
| Sharp metadata parse error | _(absent)_ | error appended — soft |
| Validation fails (no width/height/channels) | `true` | error appended |
| Corrupt/empty buffer (all fail) | `true` | multiple errors |
| Happy path | _(key absent)_ | _(key absent)_ |

**On re-run**, existing `metadata.system.etl` is deleted before merging new metadata.

**Note**: Rubiks `imageProcessor` does NOT handle thumbnails — they're a separate concern in `etlMetadataExtractor`. Thumbnail errors are not part of `etl`. We follow the same: thumbnail failures are soft (recorded but `failed` not set).

---

## 2. Current `main.py` Code (what exists today)

```
on_create(item):
  Step 1:  ENABLE_IMAGE_PREPROCESS guard → return (bare, no item)
  Step 2:  mimetype guard → return (bare, no item, no metadata written)
  Step 3:  file size guard → return (bare, no item)
  Step 4:  download → BytesIO (raises on failure)
  Step 5:  Image.open(buffer) (raises on failure — unhandled)
  Step 6:  width, height, channels from img.size / getbands()
  Step 7:  try extract_exif + extract_gps → except: metadata_failed=True
  Step 8-9: try thumbnail pipeline → except: thumbnail_failed=True
  Step 10: build_metadata() → meta dict
  Step 11-12: merge meta into item.metadata.system/user
           if metadata_failed: set item.metadata["system"]["image-preprocess-fail"]
  Step 13: item.update(system_metadata=True)
  Step 14: if metadata_failed and thumbnail_failed: raise ValueError
```

Problems:
- Steps 1-3 `return` without returning `item` (bare return)
- Step 2: unsupported mimetype writes nothing to item
- Step 5: corrupt image → unhandled exception crashes FaaS
- Step 7: EXIF failure recorded as `metadata_failed` (wrong — EXIF is non-critical)
- Step 14: raises ValueError instead of recording failure
- `"image-preprocess-fail"` key instead of `etl` dict

---

## 3. Changes to `main.py`

### 3a) Fix all bare `return` → `return item`

Steps 1, 2, 3 currently do `return` (None). Change to `return item`.

### 3b) Unsupported mimetype → write `etl: {failed: true}`, update item

**Before:**
```python
if not mimetype.startswith("image/"):
    logger.info(f"Skipping non-image item: {mimetype}")
    return
```

**After:**
```python
if not mimetype.startswith("image/"):
    logger.info(f"Skipping non-image item: {mimetype}")
    item.metadata.setdefault("system", {}).pop("etl", None)
    item.metadata["system"]["etl"] = {"failed": True}
    item = item.update(system_metadata=True)
    return item
```

### 3c) Wrap Image.open + dimension extraction in try/except

**Before** (steps 5-6): unhandled — raises on corrupt image.

**After:**
```python
try:
    buffer.seek(0)
    img = Image.open(buffer)
    img.load()
    width, height = img.size
    channels = len(img.getbands())
except Exception as e:
    logger.exception(f"Failed to open/read image for item {item.id}")
    item.metadata.setdefault("system", {}).pop("etl", None)
    item.metadata["system"]["etl"] = {
        "failed": True,
        "errors": [f"Image metadata extraction failed: {e}"],
    }
    item = item.update(system_metadata=True)
    buffer.close()
    return item
```

### 3d) Add `etl_info = {}` accumulator

After image is successfully opened:
```python
etl_info = {}
```

### 3e) EXIF failure → soft error (not `metadata_failed`)

**Before:**
```python
except Exception as e:
    logger.exception(f"Failed to extract metadata for item {item.id}")
    metadata_failed = True
    metadata_error = str(e)
    exif_data = None
    gps_data = None
```

**After:**
```python
except Exception as e:
    logger.exception(f"Failed to extract EXIF for item {item.id}")
    etl_info.setdefault("errors", []).append(f"Exif extraction failed: {e}")
    exif_data = None
    gps_data = None
```

EXIF failure is **not** a hard failure. Dimensions are already extracted. This matches Rubiks where exifr failure is soft.

### 3f) Thumbnail failure → soft error in `etl_info`

**Before:**
```python
except Exception as e:
    logger.exception(f"Failed to generate thumbnail for item {item.id}")
    thumbnail_failed = True
    thumbnail_error = str(e)
```

**After:**
```python
except Exception as e:
    logger.exception(f"Failed to generate thumbnail for item {item.id}")
    etl_info.setdefault("errors", []).append(f"Thumbnail generation failed: {e}")
```

No `failed` flag — thumbnail is non-critical (matches Rubiks where thumbnails are outside `imageProcessor`).

### 3g) Remove `metadata_failed` / `thumbnail_failed` variables and `"image-preprocess-fail"` key

**Delete:**
```python
metadata_failed = False
metadata_error = None
thumbnail_failed = False
thumbnail_error = None
```

**Delete:**
```python
if metadata_failed:
    item.metadata["system"]["image-preprocess-fail"] = metadata_error
```

### 3h) Clear old ETL + write new ETL before `item.update()`

**Add** (before `item.update()`):
```python
# Clear stale ETL from previous runs
item.metadata["system"].pop("etl", None)

# Write ETL info only if there were issues
if etl_info:
    item.metadata["system"]["etl"] = etl_info
```

### 3i) Remove `raise ValueError` at the end

**Delete:**
```python
if metadata_failed and thumbnail_failed:
    raise ValueError(...)
```

Failures are recorded, not raised. The item is updated and returned with `etl` info.

### 3j) Ensure `item = item.update(...)` (reassign)

Current code: `item.update(system_metadata=True)` — doesn't reassign. Change to:
```python
item = item.update(system_metadata=True)
return item
```

---

## 4. Updated Flow

```
on_create(item):
  1. guard: ENABLE_IMAGE_PREPROCESS disabled → return item
  
  2. guard: mimetype not image/* →
       clear old etl, set etl={failed:True}, item.update(), return item
  
  3. guard: file size exceeded → return item
  
  4. download → BytesIO (failure still raises — can't do anything without data)
  
  5. try: Image.open + load + width/height/channels
     except → write etl={failed:True, errors:[...]}, item.update(), return item
  
  etl_info = {}
  
  6. try: extract_exif + extract_gps
     except → append "Exif extraction failed: ..." (soft)
  
  7. if ENABLE_THUMBNAIL: try thumbnail pipeline
     except → append "Thumbnail generation failed: ..." (soft)
  
  8. build_metadata() + merge into item.metadata.system/user
  
  9. clear old item.metadata.system.etl
  10. if etl_info → item.metadata.system.etl = etl_info
  
  11. item = item.update(system_metadata=True)
  12. return item
  
  finally: img.close(), buffer.close()
```

---

## 5. Error String Format

| Error source | String format |
|---|---|
| Image open/load/dimensions | `"Image metadata extraction failed: {error}"` |
| EXIF extraction | `"Exif extraction failed: {error}"` |
| Thumbnail generation | `"Thumbnail generation failed: {error}"` |

---

## 6. When `etl.failed` is Set

| Condition | `failed` | Rationale |
|---|---|---|
| Non-image mimetype | `True` | Can't process — matches Rubiks unsupported format |
| Image.open/load fails | `True` | Corrupt — no dimensions possible |
| EXIF fails only | not set | Non-critical — matches Rubiks |
| Thumbnail fails only | not set | Non-critical |
| Happy path | key absent | No `etl` key — matches Rubiks |

---

## 7. Behavioral Changes

| Before | After |
|---|---|
| Bare `return` (returns None) on guards | `return item` |
| Unsupported mimetype: silent skip | Write `etl: {failed: true}`, `item.update()` |
| Corrupt image: unhandled crash | Catch → `etl: {failed: true, errors: [...]}` |
| EXIF fail = `metadata_failed` (treated as critical) | Soft error in `etl.errors` (non-critical) |
| `"image-preprocess-fail"` string key | `"etl"` dict |
| `raise ValueError` on double failure | Never raise — record in `etl` |
| No re-run cleanup | Clear old `etl` before writing |

---

## 8. Tests to Add/Modify

| Test | Assert |
|---|---|
| Unsupported mimetype | `etl == {"failed": True}`, `item.update()` called |
| Corrupt image | `etl["failed"] == True`, `etl["errors"]` has 1 entry |
| EXIF fails, image valid | `"errors"` has 1 entry, `"failed" not in etl`, width/height present |
| Thumbnail fails only | `"errors"` has 1 entry, `"failed" not in etl`, width/height present |
| Both EXIF + thumbnail fail | `"errors"` has 2 entries, `"failed" not in etl` |
| Happy path | `"etl" not in item.metadata["system"]` |
| Re-run clears old etl | Pre-set stale `etl`, run, verify `"etl" not in system` |

---

## 9. Files Changed

| File | Change |
|---|---|
| `main.py` | ETL accumulation, unsupported-format ETL, corrupt-image catch, clear-on-rerun, remove `metadata_failed`/`thumbnail_failed`/`image-preprocess-fail`/`raise ValueError`, fix bare returns |
| `tests/test_integration.py` | New/modified tests per §8 |

Two files. No new modules.
