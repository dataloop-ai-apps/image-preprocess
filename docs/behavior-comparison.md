
# Image Preprocessing — Behavior Comparison & Merged Specification

## 1. Overview

This document compares three implementations of image preprocessing:

| # | System | Language | Architecture |
|---|--------|----------|-------------|
| **A** | **Rubiks** (Node.js) | TypeScript | Inline in upload stream (ETL pipeline) |
| **B** | **image-preprocess** (this repo — current) | Python | Dataloop FaaS service triggered on item create |
| **C** | **image-preprocess** (this repo — target) | Python | Optimized replacement — same trigger model |

The goal is to define **C** by merging the best behaviors of A and B, closing gaps, and removing redundancies.

---

## 2. Architecture Comparison

| Aspect | Rubiks (A) | Current Python (B) |
|--------|-----------|-------------------|
| **Trigger** | Inline during upload stream | Dataloop trigger on `Item.Created` / `Item.Clone` (fires when `metadata.system.etl.failed == true`) |
| **Data flow** | Captures first chunk of upload stream → processes inline | Downloads the full item to local disk → processes → uploads thumbnail → updates item metadata |
| **Libraries** | `sharp` (libvips), `exifr`, `file-type` | `Pillow` (PIL), `exiftool` (CLI via `PyExifTool`), Pillow's built-in EXIF |
| **Thumbnail storage** | Uploads to `/.dataloop/thumbnails/{itemId}.png` | Uploads to `/.dataloop/thumbnails/{itemId}.{ext}` |
| **Metadata linkage** | Sets `metadata.system.thumbnailId` | Sets `metadata.system.thumbnailId` |
| **Dimension verification** | None | ✅ Cross-checks Pillow dimensions against exiftool; flags mismatch in `metadata.system.image-preprocess-fail` |
| **Error handling** | Errors captured per-stage; upload continues | Per-stage success booleans; raises `ValueError` if any stage fails |
| **Cleanup** | N/A (stream-based) | Deletes local `tmp/{itemId}/` folder in `finally` block |
| **Retry** | N/A | `NUM_TRIES = 3` in test function (not in main flow) |

---

## 3. Feature-by-Feature Comparison

### 3.1 Metadata Extraction

| Field | Rubiks (A) | Current Python (B) | Notes |
|-------|-----------|-------------------|-------|
| **Width** | `sharp.metadata().width` | `img.size[0]` (Pillow) + exiftool cross-check | B is more robust — validates with exiftool |
| **Height** | `sharp.metadata().height` | `img.size[1]` (Pillow) + exiftool cross-check | Same |
| **Channels** | `sharp.metadata().channels` | `len(img.getbands())` | ✅ Parity |
| **EXIF Orientation** | `exifr` | `Pillow._getexif()` → `ExifTags.TAGS` | ✅ Parity — both extract orientation |
| **GPS (lat/lon/alt)** | `exifr` (auto-parses GPS IFD) | `Pillow._getexif()` → `GPSTAGS` + manual DMS→DD conversion | ✅ Both extract GPS. B has explicit DMS→decimal conversion with direction handling |
| **GPS storage location** | Not specified | Stored in BOTH `metadata.system.location` AND `metadata.user.location` | B stores in two places |
| **Camera make/model** | ✅ Yes (exifr) | ❌ Not extracted | Gap — B only extracts Orientation from EXIF |
| **ISO** | ✅ Yes | ❌ Not extracted | Gap |
| **Aperture** | ✅ Yes | ❌ Not extracted | Gap |
| **Shutter speed** | ✅ Yes | ❌ Not extracted | Gap |
| **White balance** | ✅ Yes | ❌ Not extracted | Gap |
| **Date/time** | ✅ Yes | ❌ Not extracted | Gap |
| **Lens info** | ✅ Yes | ❌ Not extracted | Gap |
| **Focal length** | ✅ Yes | ❌ Not extracted | Gap |
| **Dimension cross-check** | ❌ No | ✅ Yes (Pillow vs exiftool) | B is better — catches corrupt/misreported dimensions |
| **MIME type detection** | `file-type` (magic bytes) | Uses `item.mimetype` from platform | Different approach |

### 3.2 Thumbnail Generation

| Aspect | Rubiks (A) | Current Python (B) | Notes |
|--------|-----------|-------------------|-------|
| **Default size** | 512×512 | **128×128** | ✅ Aligned |
| **Resize method** | `sharp.resize()` (fit: inside) | `Image.thumbnail()` (preserves aspect ratio) | Both preserve aspect ratio |
| **Output format** | Always PNG | JPG for JPEG inputs, PNG for everything else | B is smarter — preserves format for JPEG |
| **EXIF auto-rotate** | Via sharp (automatic) | Manual `rotating()` method with orientation map | ✅ Both handle it, B is explicit |
| **TIFF handling** | Generated normally | ⛔ **Skipped entirely** (`if 'tif' not in mimetype`) | B skips thumbnails for TIFF |
| **Stream processing** | ✅ Pipes through stream | ❌ Full file download to disk first | Architectural difference |
| **Thumbnail upload** | `/.dataloop/thumbnails/{itemId}.png` | `/.dataloop/thumbnails/{itemId}.{jpg|png}` | Minor path difference |
| **Upload metadata** | Not specified | Sets `system.originItemId` on thumbnail item | B adds lineage |
| **Overwrite** | Not specified | `overwrite=True` | B explicitly overwrites existing thumbnails |

### 3.3 Metadata Written to Item

**Current Python (B) writes:**

```
metadata.system.exif          = { Orientation: <int> }   (only orientation!)
metadata.system.width         = <int>
metadata.system.height        = <int>
metadata.system.channels      = <int>
metadata.system.thumbnailId   = <string>
metadata.system.location      = { latitude, longitude, altitude }
metadata.user.location        = { latitude, longitude, altitude }   (duplicate!)
```

**Rubiks (A) writes:**

```
metadata.system.thumbnailId   = <string>
(+ EXIF data via exifr — exact structure varies)
(+ width, height, channels via sharp)
```

---

## 4. Key Gaps & Issues Summary

| # | Issue | Severity | Source | Description |
|---|-------|----------|--------|-------------|
| G1 | **Camera/capture EXIF not extracted** | Medium | B vs A | B only extracts Orientation from EXIF; misses camera model, ISO, aperture, shutter, white balance, date, lens, focal length |
| G2 | **Thumbnail size mismatch** | High | B vs A | B uses 128×128, Rubiks uses 512×512. Need to align or make configurable |
| G3 | **TIFF thumbnails skipped** | Medium | B only | B skips thumbnail generation for TIFF files entirely |
| G4 | **GPS stored in two places** | Low | B only | `metadata.system.location` AND `metadata.user.location` — likely intentional but duplicative |
| G5 | **ExifTool CLI dependency** | High | B only | B shells out to `exiftool` binary for dimension cross-checking. Heavy dependency for a single validation |
| G6 | **No max file size guard** | Medium | B only | No `MAX_THUMB_SIZE_MB` equivalent — will attempt to process any file size |
| G7 | **No configurable switches** | Medium | B only | No enable/disable flags for preprocessing or thumbnails |
| G8 | **Deprecated Pillow API** | Low | B only | Uses `img._getexif()` (private method) instead of `img.getexif()` |
| G9 | **Full file download** | Medium | B only | Downloads entire file to local disk; fine for normal images but wasteful for very large files |

---

## 5. Merged Target Specification (C)

### Decision Snapshot (for quick review)

1. **Baseline:** Follow Rubiks behavior by default; Python path runs only when Rubiks (A) fails.
2. **EXIF coverage:** Extract full camera/capture/lens fields in C (make/model, ISO, aperture, shutter, white balance, focal length, datetime, lens info) using Pillow.
3. **Thumbnail size:** Default bounding box **128×128**.
4. **Thumbnail format:** Always upload thumbnails as **PNG** (even for JPEG inputs) to match A.
5. **TIFF:** Process TIFFs (metadata + thumbnail as PNG) instead of skipping.
6. **Buffer to RAM (no disk write):** Fetch the item once into an in-memory `BytesIO` via `item.download(save_locally=False)` and feed both metadata extraction and thumbnail generation from that single buffer (rewind between reads). Do **not** write the source to local disk. This keeps the single-fetch guarantee, removes disk I/O and `tmp/` cleanup, and carries no RAM penalty vs. disk (see §5.10 — Performance of C). Note: Rubiks (A) processes the upload stream inline; Python (C) cannot replicate that, so buffering the downloaded bytes is the closest equivalent.
7. **Thumbnail upload metadata:** Upload thumbnail with metadata and `overwrite=true`, ensuring `metadata.system.thumbnailId` (and other generated metadata) replaces any prior value.
8. **Guards:** Enforce a max input size gate before processing.
9. **Config switches:** Keep feature flags/env toggles for preprocessing and thumbnailing.

### 5.1 Trigger & Entry Point

Same as current: Dataloop FaaS function `on_create`, triggered on `Item.Created` / `Item.Clone` for image MIME types.

```
entryPoint: main.py
className: ServiceRunner
function: on_create(item: dl.Item, progress)
```

### 5.2 Processing Pipeline

```
on_create(item)
  ├── 1. Fetch item once into RAM buffer (item.download(save_locally=False) → BytesIO)
  ├── 2. Extract metadata (Pillow reads from buffer; seek(0) first)
  │     ├── Basic: width, height, channels
  │     ├── EXIF (full): orientation, camera, capture settings, GPS, lens
  │     └── Cross-check dimensions with Pillow's own metadata (drop exiftool)
  ├── 3. Generate thumbnail (if enabled and under size limit)
  │     ├── seek(0) on the buffer to re-read the same bytes (no re-fetch)
  │     ├── Auto-rotate based on EXIF orientation
  │     ├── Resize to DEFAULT_THUMB_SIZE (default: 128×128)
  │     ├── Save as PNG for all inputs (JPEG, PNG, TIFF, etc.)
  │     └── Upload to /.dataloop/thumbnails/{itemId}.png
  ├── 4. Write metadata to item
  │     ├── metadata.system.width
  │     ├── metadata.system.height
  │     ├── metadata.system.channels
  │     ├── metadata.system.exif (structured — see 5.3)
  │     ├── metadata.system.thumbnailId
  │     └── metadata.system.location (GPS, if available)
  │     └── metadata.user.location (GPS, if available — backward compat)
  └── 5. item.update(system_metadata=True)
        (no temp folder, no disk cleanup — buffer is GC'd)
```

### 5.3 Metadata Schema — `metadata.system.exif`

The current code only stores `{ Orientation: <int> }`. The target should store a structured object:

```json
{
  "Orientation": 1,
  "camera": {
    "make": "Apple",
    "model": "iPhone 14 Pro"
  },
  "capture": {
    "iso": 100,
    "aperture": 1.78,
    "shutter_speed": "1/120",
    "focal_length": 6.86,
    "white_balance": "Auto",
    "datetime": "2024-03-15T10:30:00"
  },
  "lens": {
    "make": "Apple",
    "model": "iPhone 14 Pro back triple camera 6.86mm f/1.78"
  }
}
```

**Rules:**
- Fields that cannot be extracted are **omitted** (not set to `null`).
- Sub-objects are omitted entirely if empty.
- `Orientation` stays at the top level for backward compatibility.
- Numeric values stay numeric (not stringified).
- `shutter_speed` formatted as a fraction string (e.g., `"1/120"`).
- `datetime` in ISO 8601 format.

### 5.4 Metadata Schema — `metadata.system.location` / `metadata.user.location`

```json
{
  "latitude": 32.0853,
  "longitude": 34.7818,
  "altitude": 25.0
}
```

**Rules:**
- Latitude/longitude as decimal degrees (float).
- Altitude in meters (float), negative if below sea level (using GPSAltitudeRef).
- Fields omitted if not available.
- **Keep dual storage** (system + user) for backward compatibility.

### 5.5 Thumbnail Rules

| Parameter | Value |
|-----------|-------|
| Default size | **128×128** (bounding box, aspect ratio preserved) |
| Input → output | **PNG for all inputs** (JPEG/PNG/TIFF/etc.) |
| TIFF inputs | ✅ Generate PNG thumbnail |
| EXIF orientation | Applied before resize |
| Upload path | `/.dataloop/thumbnails/{itemId}.png` |
| Upload metadata | `{ system: { originItemId: itemId, ...thumbnailMetadata } }` |
| Overwrite | `True` (always replace prior thumbnail + metadata) |

### 5.6 Configuration (Environment Variables)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ENABLE_IMAGE_PREPROCESS` | bool | `true` | Master switch — if false, `on_create` returns immediately |
| `ENABLE_THUMBNAIL` | bool | `true` | Enable/disable thumbnail generation |
| `MAX_FILE_SIZE_MB` | int | `100` | Max input file size for processing (skip if larger) |
| `DEFAULT_THUMB_SIZE` | int | `128` | Thumbnail bounding box dimension |
| `MAX_IMAGE_PIXELS` | int | `400000000` (20000×20000) | Pillow decompression bomb guard |

### 5.7 Error Handling

| Scenario | Behavior |
|----------|----------|
| Metadata extraction fails | Log error, set `metadata.system.image-preprocess-fail`, still attempt thumbnail |
| Thumbnail generation fails | Log error, still save metadata |
| Both fail | Raise `ValueError` so execution is marked failed |
| File too large | Skip processing, log warning |
| Unsupported format | Skip processing, log warning |

### 5.8 Dependencies — Target

| Current (B) | Target (C) | Reason |
|-------------|-----------|--------|
| `Pillow` | `Pillow` | Keep — core image library |
| `PyExifTool` (shells out to `exiftool` binary) | **Remove** | Replace with Pillow's built-in `getexif()` + `get_ifd()` for sub-IFD parsing. Eliminates binary dependency |
| `exiftool` (apt package) | **Remove** | No longer needed |
| `dtlpy` | `dtlpy` | Keep — platform SDK |

The dimension cross-check currently done via exiftool can be handled by comparing Pillow's `img.size` with the EXIF `ImageWidth`/`ImageHeight` tags (available in the EXIF IFD) — no external tool needed.

### 5.9 EXIF Extraction — Implementation Approach

Use Pillow's modern EXIF API (available since Pillow 9.2):

```python
from PIL import Image
from PIL.ExifTags import Base, GPS, IFD

img = Image.open(filepath)
exif = img.getexif()

# Top-level tags
orientation = exif.get(Base.Orientation)
make = exif.get(Base.Make)
model = exif.get(Base.Model)
datetime_original = exif.get(Base.DateTimeOriginal)

# EXIF sub-IFD (IFD 0x8769)
exif_ifd = exif.get_ifd(IFD.Exif)
iso = exif_ifd.get(Base.ISOSpeedRatings)
aperture = exif_ifd.get(Base.FNumber)
shutter = exif_ifd.get(Base.ExposureTime)
focal_length = exif_ifd.get(Base.FocalLength)
white_balance = exif_ifd.get(Base.WhiteBalance)

# GPS sub-IFD (IFD 0x8825)
gps_ifd = exif.get_ifd(IFD.GPSInfo)
# Parse DMS → decimal degrees (same logic as current code)
```

This eliminates the need for `exifr`, `piexif`, `exifread`, or the `exiftool` CLI.

### 5.10 Performance of C — Why Buffer to RAM (and the Risks)

Component **C** is the Python (Pillow) path. It cannot reproduce Rubiks' (A) inline stream-during-upload behavior: A observes the same byte stream that is being written to storage, so it never re-fetches the file. C runs as an event-triggered FaaS execution **after** the item already exists in storage, so it must fetch the bytes itself. The only real choice for C is *how* it holds those fetched bytes: in RAM or on disk.

**Decision: buffer to RAM** via `item.download(save_locally=False)`, which returns a `BytesIO`. Both metadata extraction and thumbnail generation read from that single buffer (rewinding between reads). No temp file, no disk cleanup.

#### Why not write to disk first?

1. **Disk write does not reduce RAM.** The dominant memory cost is not the compressed file — it is Pillow's *decoded* bitmap. Pillow loads the full uncompressed raster into memory to read pixels or resize, regardless of whether the source came from disk or a buffer. A 3 MB JPEG at 6000×4000 RGB decodes to ~72 MB in RAM (`width × height × 3` bytes). Writing the 3 MB to disk first saves nothing against that 72 MB; it only adds I/O.
2. **Single-fetch guarantee.** The architecture requires the file be fetched exactly once and reused for both outputs. One `BytesIO` reused (with `.seek(0)`) satisfies this cleanly. A disk path would still need the same single fetch plus extra read-back I/O.
3. **No cleanup / no stateful disk.** FaaS replicas are stateless and ephemeral. Skipping disk avoids temp-dir management, partial-write leftovers on crash, and disk-pressure across concurrent executions sharing a pod's filesystem.
4. **Lower latency.** Removes two syscall round-trips (write then read) from the hot path. The compressed buffer is small relative to the decoded bitmap that must exist either way.

#### Peak RAM model

Peak RAM per execution ≈ compressed buffer + decoded bitmap + thumbnail working set:

```
peak ≈ compressed_size + (W × H × channels) + (thumb_W × thumb_H × channels)
```

The decoded bitmap term dominates. For a pod, multiply by `concurrency_per_replica`:

```
pod_peak ≈ concurrency × (W × H × channels)
```

| Source JPEG | Resolution | Decoded RGB | Notes |
|-------------|-----------|-------------|-------|
| ~2 MB | 4000×3000 | ~36 MB | typical phone photo |
| ~5 MB | 6000×4000 | ~72 MB | DSLR |
| ~3 MB | 8000×6000 | ~144 MB | high-res, still small compressed |

The compressed buffer (single-digit MB) is negligible next to the decoded raster — confirming disk-buffering the compressed bytes would not meaningfully change pod memory.

#### Performance risks (and mitigations)

- **Decompression bombs / huge pixel counts.** A small compressed file can decode to gigabytes (`W × H × channels`). This is the real OOM vector, not the byte buffer. **Mitigation:** enforce a max-pixel gate before decode and keep `PIL.Image.MAX_IMAGE_PIXELS` at a sane bound (do not disable it); reject oversized images as a partial/handled failure rather than crashing the pod.
- **Concurrency × decoded size under bulk load.** During a 1M-image burst the autoscaler spins many replicas; each concurrent decode holds a full bitmap. **Mitigation:** size pod RAM against `concurrency × worst-case decoded bitmap`, not against file size; prefer modest `concurrency_per_replica` so one large image cannot OOM the pod.
- **`exiftool` subprocess overhead (current B).** Shelling out to `exiftool` per item adds process-spawn latency and a second read of the bytes, and complicates the RAM/disk story. **Mitigation:** removed in C (Phase 1/5) — EXIF comes from Pillow `getexif()`/`get_ifd()` reading the same in-memory buffer, so there is no separate file path or subprocess.
- **Buffer reuse bugs.** Reading the same `BytesIO` twice without rewinding yields empty/partial reads. **Mitigation:** `buffer.seek(0)` before each consumer (metadata, then thumbnail).
- **No streaming/early-abort.** Unlike A, C holds the whole compressed file before processing; it cannot reject by MIME mid-stream. Acceptable for standard image sizes; the max-size gate bounds the downside.

---

## 6. Format Support

| Format | Metadata | Thumbnail | Notes |
|--------|----------|-----------|-------|
| JPEG | ✅ | ✅ (output: PNG) | Always emit PNG thumbnail |
| PNG | ✅ | ✅ (output: PNG) | |
| WebP | ✅ | ✅ (output: PNG) | Pillow supports WebP |
| BMP | ✅ | ✅ (output: PNG) | |
| GIF | ✅ | ✅ (first frame, output: PNG) | |
| TIFF | ✅ | ✅ (output: PNG) | Now generate thumbnails for TIFF |
| AVIF | ⚠️ | ⚠️ | Requires Pillow ≥10.1 or `pillow-avif-plugin` |
| SVG | ❌ | ❌ | Not supported by Pillow — out of scope |

---

## 7. Behavioral Differences — Intentional Deviations from Rubiks

These are deliberate choices for the Python implementation:

1. **Fetch-once into a RAM buffer:** C cannot stream-during-upload like A (it runs post-upload as a FaaS event), so it fetches the item once into a `BytesIO` (`item.download(save_locally=False)`) and reuses that buffer for both metadata and thumbnail. No disk write — disk would not lower peak RAM (Pillow's decoded bitmap dominates). See §5.10.
2. **Dimension cross-validation:** Current Python code validates Pillow dimensions against exiftool. Target replaces exiftool with EXIF IFD comparison but keeps the validation concept.
3. **Thumbnail output format:** Always emit PNG thumbnails (align with Rubiks) even for JPEG inputs.
4. **TIFF thumbnails:** Now generated (PNG) instead of skipped.
5. **Dual GPS storage:** GPS in both `system.location` and `user.location`. Kept for backward compatibility even though it's redundant.

---

## 8. Implementation Plan

| Phase | Task | Closes Gap |
|-------|------|-----------|
| **Phase 1** | Remove `exiftool`/`PyExifTool` dependency; implement EXIF extraction via Pillow `getexif()` + `get_ifd()` | G5, G8 |
| **Phase 2** | Extract full EXIF metadata (camera, capture, lens) into structured `metadata.system.exif` | G1 |
| **Phase 3** | ~~Change default thumbnail size from 128 to 512~~ | ~~G2~~ |
| **Phase 4** | Add configuration via environment variables | G6, G7 |
| **Phase 5** | Implement dimension cross-check using EXIF IFD (replace exiftool check) | G5 |
| **Phase 6** | Add partial failure handling (metadata success + thumbnail failure = partial success) | — |
| **Phase 7** | Update Dockerfile (remove `apt-get install exiftool` and `pip install PyExifTool`) | G5 |
| **Phase 8** | Add unit tests | — |

---

## 9. Out of Scope (v1)

- SVG rasterization
- Video frame extraction
- Multi-page TIFF thumbnail generation
- Animated GIF multi-frame thumbnails
- Streaming/chunked input processing
- ICC color profile extraction
- IPTC/XMP metadata extraction
