
# Implementation Plan — Merged Target Specification (C)

## Status: READY FOR IMPLEMENTATION 📋

## Philosophy

Treat the repo as a **framework with fixed entry points** (`ServiceRunner.on_create` via Dataloop FaaS).
We are **rewriting the internals from scratch** — the existing module code is irrelevant.
Only the contract matters: entry point signature (`on_create(item, progress)`), Dataloop SDK interactions, Docker base image.

The spec is defined in `docs/behavior-comparison.md` §5 ("Merged Target Specification"). This plan breaks that spec into implementable phases.

---

## 1. Target File Structure

```
image-preprocess/
├── main.py                      # ServiceRunner — orchestrator only
├── modules/
│   ├── __init__.py
│   ├── exif_extractor.py        # Pure-Pillow EXIF extraction (all fields)
│   ├── thumbnail.py             # Auto-rotate + 512-longest-edge PNG thumbnail
│   └── metadata.py              # Schema builder: raw data → final metadata dicts
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Shared fixtures (sample images, mock dl.Item)
│   ├── test_exif_extractor.py
│   ├── test_thumbnail.py
│   ├── test_metadata.py
│   └── test_integration.py      # Full on_create pipeline with mocked Dataloop SDK
├── tests/fixtures/
│   └── README.md                # How fixtures are generated / sourced
├── docs/
│   └── behavior-comparison.md   # Existing — source of truth for spec
├── .plans/
│   ├── initial-analysis.md
│   └── implementation-plan.md   # This file
├── Dockerfile
├── dataloop.json
├── requirements.txt
└── .gitignore
```

### Files to CREATE from scratch
- `modules/__init__.py`
- `modules/exif_extractor.py`
- `modules/thumbnail.py`
- `modules/metadata.py`
- `tests/__init__.py`
- `tests/conftest.py`
- `tests/test_exif_extractor.py`
- `tests/test_thumbnail.py`
- `tests/test_metadata.py`
- `tests/test_integration.py`
- `tests/fixtures/README.md`

### Files to REWRITE
- `main.py` — complete rewrite (same class/method signature)
- `requirements.txt` — stripped down
- `Dockerfile` — remove exiftool

### Files to EVALUATE for deletion
- `modules/exif_utils.py`, `modules/image_utils.py` — replaced by new modules
- `to_delete/` directory
- `application_deployment.py`, `infra.py`, `results/`, `build-docker.sh`
- `dataloop_ford.json`, `dataloop_syngenta.json` — customer-specific configs

---

## 2. Implementation Phases

---

### Phase 0: Test Infrastructure (`tests/conftest.py` + fixtures)

**Goal**: Build the test scaffolding before any production code. Tests drive the implementation.

**`conftest.py` provides**:

1. **`create_test_image(width, height, mode="RGB", exif=None, gps=None)`** — Programmatically creates a Pillow Image with optional EXIF data baked in. Returns a `BytesIO` buffer containing the saved JPEG/PNG.

2. **Pre-built fixture images** (pytest fixtures):
   - `landscape_jpeg` — 800×600 JPEG, full EXIF (make, model, ISO, aperture, exposure, focal, lens, flash, whiteBalance, orientation=1, GPS)
   - `portrait_rotated_jpeg` — 600×800 JPEG but saved as 800×600 with orientation=6 (90° CW)
   - `no_exif_png` — 400×300 PNG, no EXIF at all
   - `small_jpeg` — 100×80 JPEG, minimal EXIF (orientation only)
   - `rgba_png` — 400×300 RGBA PNG
   - `tiff_image` — 400×300 TIFF (single page)

3. **`mock_dl_item`** — Factory fixture that creates a `MagicMock` mimicking `dl.Item`:
   - `.id` = configurable
   - `.name` = configurable
   - `.datasetId` = `"test-dataset-id"`
   - `.metadata` = `{"system": {"mimetype": "image/jpeg"}, "user": {}}`
   - `.download(save_locally=False)` returns a `BytesIO` buffer
   - `.update(system_metadata=True)` is a mock

4. **`mock_dl_progress`** — Mock with `.logger` attribute:
   - `.logger.info()`, `.logger.warning()`, `.logger.error()`, `.logger.exception()` — all mocks

5. **`mock_dataset`** — Mock for `dl.datasets.get()` → `.items.upload()` returns a mock thumbnail item with `.id`

**Hard questions**:
- Q1: Can Pillow programmatically write EXIF with GPS IFD into a JPEG in-memory? → Yes, via `img.save(buf, exif=exif_bytes)` where `exif_bytes` from `Exif().tobytes()`. GPS IFD requires `exif.get_ifd(IFD.GPSInfo)` manipulation. If too brittle for test setup, commit a small real JPEG with known EXIF instead.
- Q2: How does `item.download(save_locally=False)` actually work? → Need to verify against dtlpy SDK. Plan assumes it returns `bytes`; we wrap in `BytesIO`.

---

### Phase 1: `modules/exif_extractor.py` — EXIF Extraction Engine

**Goal**: Pure functions. Take a Pillow `Image`, return structured EXIF and GPS data. No side effects, no Dataloop SDK dependency.

#### Public API

```python
def extract_exif(img: Image.Image) -> dict | None:
    """Extract EXIF metadata from a Pillow Image.
    
    Returns a dict with snake_case keys for present fields,
    or None if no EXIF data exists at all.
    """

def extract_gps(img: Image.Image) -> dict | None:
    """Extract GPS coordinates from EXIF.
    
    Returns {"latitude": float, "longitude": float, "altitude": float}
    or None if GPS data is absent/incomplete (both lat+lon required).
    Latitude/longitude are signed decimal degrees (S/W = negative).
    Altitude is meters; negative if below sea level (GPSAltitudeRef=1).
    Altitude is optional within the returned dict.
    """
```

#### `extract_exif` Return Schema (only present keys included)

```python
{
    "orientation": int,            # 1-8
    "camera_make": str,            # e.g. "Apple"
    "camera_model": str,           # e.g. "iPhone 15 Pro"
    "date_time": str,              # e.g. "2024:01:15 10:30:45"
    "iso": int,                    # e.g. 100
    "aperture": float,             # f-number, 2dp, e.g. 1.78
    "exposure_time": str,          # rational string, e.g. "1/120"
    "focal_length": float,         # mm, e.g. 6.765
    "focal_length_35mm": int,      # mm equivalent, e.g. 24
    "lens_model": str,             # e.g. "iPhone 15 Pro back camera 6.765mm f/1.78"
    "flash": bool,                 # True if fired (bit 0 of Flash tag)
    "white_balance": int,          # 0 = auto, 1 = manual
}
```

#### `extract_gps` Return Schema

```python
{
    "latitude": float,             # signed decimal degrees
    "longitude": float,            # signed decimal degrees
    "altitude": float,             # meters (optional key)
}
```

#### Implementation Approach (per §5.9)

Use Pillow's modern EXIF API with named constants:

```python
from PIL import Image
from PIL.ExifTags import Base, GPS, IFD

exif = img.getexif()

# Main IFD
orientation = exif.get(Base.Orientation)
make = exif.get(Base.Make)
model = exif.get(Base.Model)

# EXIF sub-IFD (IFD 0x8769)
exif_ifd = exif.get_ifd(IFD.Exif)
iso = exif_ifd.get(Base.ISOSpeedRatings)
aperture = exif_ifd.get(Base.FNumber)
shutter = exif_ifd.get(Base.ExposureTime)
focal_length = exif_ifd.get(Base.FocalLength)
white_balance = exif_ifd.get(Base.WhiteBalance)
# ... etc

# GPS sub-IFD (IFD 0x8825)
gps_ifd = exif.get_ifd(IFD.GPSInfo)
```

**EXIF Tag Map**:

| Field | IFD | Pillow Constant | Tag ID |
|-------|-----|-----------------|--------|
| Orientation | Main | `Base.Orientation` | 274 |
| Make | Main | `Base.Make` | 271 |
| Model | Main | `Base.Model` | 272 |
| DateTimeOriginal | ExifIFD | `Base.DateTimeOriginal` | 36867 |
| ISO | ExifIFD | `Base.ISOSpeedRatings` | 34855 |
| FNumber | ExifIFD | `Base.FNumber` | 33437 |
| ExposureTime | ExifIFD | `Base.ExposureTime` | 33434 |
| FocalLength | ExifIFD | `Base.FocalLength` | 37386 |
| FocalLength35mm | ExifIFD | `Base.FocalLengthIn35mmFilm` | 41989 |
| LensModel | ExifIFD | `Base.LensModel` | 42036 |
| Flash | ExifIFD | `Base.Flash` | 37385 |
| WhiteBalance | ExifIFD | `Base.WhiteBalance` | 41987 |

| GPS Field | Pillow Constant | Tag ID |
|-----------|-----------------|--------|
| GPSLatitudeRef | `GPS.GPSLatitudeRef` | 1 |
| GPSLatitude | `GPS.GPSLatitude` | 2 |
| GPSLongitudeRef | `GPS.GPSLongitudeRef` | 3 |
| GPSLongitude | `GPS.GPSLongitude` | 4 |
| GPSAltitudeRef | `GPS.GPSAltitudeRef` | 5 |
| GPSAltitude | `GPS.GPSAltitude` | 6 |

**Value conversion rules**:
- `IFDRational` (FNumber, ExposureTime, FocalLength, GPSAltitude) → use `.numerator` / `.denominator`
- ExposureTime → string: if denominator > 1 → `"{num}/{den}"`, else `str(float(value))`
- FNumber → `round(float(value), 2)`
- FocalLength → `round(float(value), 3)`
- Flash → `bool(value & 1)` (bit 0 = fired)
- WhiteBalance → `int(value)` (0=auto, 1=manual)
- String tags → `.strip().strip('\x00')`
- GPS DMS → DD: `degrees + minutes/60 + seconds/3600`, negate if ref is S or W
- GPS altitude: `float(value)`, negate if `GPSAltitudeRef == 1`
- ISO as tuple (some cameras) → take first element

**Error isolation**: Each field extraction wrapped in its own try/except. One bad tag must NOT prevent extraction of others. Log warnings for parse failures.

**Edge cases**:
- No EXIF at all (PNG) → both functions return `None`
- EXIF present but ExifIFD empty → only main IFD tags extracted
- GPS with only lat (no lon) → `extract_gps()` returns `None` (both required)
- IFDRational with zero denominator → skip that field
- ISO as tuple → take `value[0]` if tuple/list

#### Tests (`test_exif_extractor.py`)

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Full EXIF extraction | JPEG with all tags | Dict with all fields, correct values |
| 2 | No EXIF | PNG | Returns `None` |
| 3 | Partial EXIF | JPEG with only orientation | Dict with only `orientation` key |
| 4 | GPS extraction — northern/eastern | lat_ref=N, lon_ref=E | Positive lat, positive lon |
| 5 | GPS — southern hemisphere | lat_ref=S | Negative latitude |
| 6 | GPS — western hemisphere | lon_ref=W | Negative longitude |
| 7 | GPS — incomplete (lat only) | No longitude | Returns `None` |
| 8 | GPS — with altitude | altitude + ref=0 | Positive altitude |
| 9 | GPS — altitude below sea level | ref=1 | Negative altitude |
| 10 | Flash fired | Flash=1 | `flash: True` |
| 11 | Flash not fired | Flash=0 | `flash: False` |
| 12 | Flash with red-eye | Flash=65 | `flash: True` (bit 0) |
| 13 | ExposureTime formatting | 1/120 | `"1/120"` |
| 14 | ExposureTime ≥ 1 second | 2.5s | `"5/2"` or `"2.5"` |
| 15 | WhiteBalance auto | value=0 | `white_balance: 0` |
| 16 | WhiteBalance manual | value=1 | `white_balance: 1` |
| 17 | Null bytes in string tag | `"Apple\x00"` | `"Apple"` |
| 18 | Corrupt EXIF — partial | One tag unreadable | Other tags still extracted |

---

### Phase 2: `modules/thumbnail.py` — Thumbnail Generation

**Goal**: Auto-rotate an image, produce a 512-longest-edge PNG thumbnail as a `BytesIO` buffer.

#### Public API

```python
from PIL import Image
from io import BytesIO

def auto_rotate(img: Image.Image) -> Image.Image:
    """Apply EXIF orientation and return a new correctly-oriented image.
    If no orientation tag or error, returns the image unchanged (copy)."""

def generate_thumbnail(img: Image.Image, max_edge: int = 512) -> BytesIO:
    """Generate a PNG thumbnail fitting within max_edge × max_edge.
    
    Input image should already be auto-rotated.
    Does NOT upscale — if image is smaller than max_edge, keeps original size.
    Converts to RGB if necessary (handles RGBA, P, L, LA, CMYK).
    Returns a BytesIO buffer containing PNG data, seeked to 0.
    """
```

#### Implementation Details

**`auto_rotate`**:
- Use `PIL.ImageOps.exif_transpose(img)` — handles all 8 orientation values.
- Returns a new image. If `exif_transpose` raises or returns None → return `img.copy()`.
- Always returns a copy — never mutates input.

**`generate_thumbnail`**:
- `thumb = img.copy()` — never mutate the input.
- `thumb.thumbnail((max_edge, max_edge), Image.LANCZOS)` — Pillow fits within bounding box, preserves aspect ratio, never upscales.
- Mode conversion before save:
  - RGBA → composite over white background, then convert to RGB.
  - P (palette) → convert to RGBA first (may have transparency), then composite over white → RGB.
  - LA → composite over white → convert to RGB.
  - CMYK → direct convert to RGB.
  - L → keep as L (valid in PNG).
- Save to `BytesIO` as PNG: `thumb.save(buf, format="PNG")`.
- `buf.seek(0)` before returning.

**RGBA → RGB compositing**:
```python
background = Image.new("RGB", thumb.size, (255, 255, 255))
background.paste(thumb, mask=thumb.split()[3])
thumb = background
```

**Animated images** (GIF, WEBP):
- Only process the first frame. `img.seek(0)` then `.copy()`.

#### Tests (`test_thumbnail.py`)

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Landscape resize | 4032×3024 | 512×384 |
| 2 | Portrait resize | 3024×4032 | 384×512 |
| 3 | Square resize | 2000×2000 | 512×512 |
| 4 | Small image — no upscale | 100×80 | 100×80 (unchanged) |
| 5 | Custom max_edge | 4032×3024, max_edge=256 | 256×192 |
| 6 | RGBA → RGB | 400×300 RGBA | RGB PNG, white background |
| 7 | Auto-rotate orientation=6 | 800×600 saved, tag=6 | Result is 600×800 |
| 8 | Auto-rotate orientation=1 | Normal | Unchanged dimensions |
| 9 | Auto-rotate no EXIF | PNG | Unchanged |
| 10 | Output is valid PNG | Any | `Image.open(result)` succeeds, format=="PNG" |
| 11 | Output buffer seeked to 0 | Any | `result.tell() == 0` |
| 12 | Input not mutated | Any | Original Image unchanged after call |

---

### Phase 3: `modules/metadata.py` — Metadata Schema Builder

**Goal**: Take raw extracted data and build the exact metadata dicts that get written to `item.metadata`. Pure function, no Dataloop SDK dependency.

#### Public API

```python
def build_metadata(
    width: int,
    height: int,
    channels: int,
    thumbnail_id: str | None,
    exif_data: dict | None,
    gps_data: dict | None,
) -> dict:
    """Build a dict describing what to merge into item.metadata.
    
    Returns:
    {
        "system": { ... },   # always present
        "user": { ... },     # only if GPS data present (backward compat)
    }
    """
```

#### Return Schema

```python
{
    "system": {
        "width": 4032,
        "height": 3024,
        "channels": 3,
        "thumbnailId": "abc123",          # only if thumbnail_id is not None
        "exif": {                          # only if exif_data has fields
            "orientation": 1,
            "cameraMake": "Apple",
            "cameraModel": "iPhone 15 Pro",
            "dateTime": "2024:01:15 10:30:45",
            "iso": 100,
            "aperture": 1.78,
            "exposureTime": "1/120",
            "focalLength": 6.765,
            "focalLength35mm": 24,
            "lensModel": "...",
            "flash": false,
            "whiteBalance": 0
        },
        "location": {                      # only if gps_data is not None
            "latitude": 32.0853,
            "longitude": 34.7818,
            "altitude": 15.0              # optional within location
        }
    },
    "user": {                              # only if gps_data is not None
        "location": {
            "latitude": 32.0853,
            "longitude": 34.7818,
            "altitude": 15.0
        }
    }
}
```

**NOTE**: GPS is stored in **both** `system.location` and `user.location` for backward compatibility (per spec §5.4).

#### EXIF Key Mapping (snake_case → camelCase)

| Input key | Output key |
|-----------|------------|
| `orientation` | `orientation` |
| `camera_make` | `cameraMake` |
| `camera_model` | `cameraModel` |
| `date_time` | `dateTime` |
| `iso` | `iso` |
| `aperture` | `aperture` |
| `exposure_time` | `exposureTime` |
| `focal_length` | `focalLength` |
| `focal_length_35mm` | `focalLength35mm` |
| `lens_model` | `lensModel` |
| `flash` | `flash` |
| `white_balance` | `whiteBalance` |

**Rules**:
- Only include keys from `exif_data` that are actually present (no `None` values).
- If `exif_data` is `None` or empty after mapping → omit `"exif"` key entirely.
- If `gps_data` is `None` → omit both `"location"` in system AND `"user"` dict entirely.
- No `null` values anywhere in output.
- No `aspectRatio` (per spec §5.3 — "No aspectRatio").
- `thumbnailId` only if `thumbnail_id` is not None.

#### Tests (`test_metadata.py`)

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Full data | All fields present | Full output with system + user |
| 2 | No EXIF, no GPS | `exif_data=None, gps_data=None` | No `exif`, no `location`, no `user` |
| 3 | EXIF but no GPS | Partial exif | `exif` present, no `location`, no `user` |
| 4 | GPS but no EXIF | Only GPS | `location` in system + user, no `exif` |
| 5 | Partial EXIF | Only orientation + ISO | Only those two in `exif` dict |
| 6 | Empty EXIF dict | `exif_data={}` | No `exif` key (empty → omit) |
| 7 | GPS with altitude | lat, lon, alt | All three in both locations |
| 8 | GPS without altitude | lat, lon only | Only lat, lon in both locations |
| 9 | Key mapping correctness | All snake_case keys | All correctly camelCased |
| 10 | No thumbnailId | `thumbnail_id=None` | No `thumbnailId` key in system |
| 11 | No null values | Mixed data | Assert no None values anywhere in output |

---

### Phase 4: `main.py` — Orchestrator Rewrite

**Goal**: Clean `ServiceRunner` that wires modules together. Minimal logic — delegates everything to modules.

#### Class Structure

```python
import logging
import os
from io import BytesIO

import dtlpy as dl
from PIL import Image

from modules.exif_extractor import extract_exif, extract_gps
from modules.thumbnail import auto_rotate, generate_thumbnail
from modules.metadata import build_metadata

logger = logging.getLogger(__name__)

# Configuration (§5.6)
ENABLE_IMAGE_PREPROCESS = os.getenv("ENABLE_IMAGE_PREPROCESS", "true").lower() == "true"
ENABLE_THUMBNAIL = os.getenv("ENABLE_THUMBNAIL", "true").lower() == "true"
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
DEFAULT_THUMB_SIZE = int(os.getenv("DEFAULT_THUMB_SIZE", "128"))
MAX_IMAGE_PIXELS = int(os.getenv("MAX_IMAGE_PIXELS", "400000000"))


class ServiceRunner(dl.BaseServiceRunner):
    def __init__(self, **kwargs):
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

    def on_create(self, item: dl.Item, progress=None):
        ...
```

#### Pipeline (`on_create`) — Step by Step

```
Step 1:  ENABLE_IMAGE_PREPROCESS check → if False, return immediately
Step 2:  MIME guard → if not image/* → return
Step 3:  File size guard → if item size > MAX_FILE_SIZE_MB → log warning, return
Step 4:  Download to BytesIO → buffer = item.download(save_locally=False)
         Wrap in BytesIO if raw bytes returned
Step 5:  Open with Pillow → img = Image.open(buffer)
Step 6:  Extract basic dimensions → width, height = img.size; channels = len(img.getbands())

--- Metadata extraction (non-fatal block) ---
Step 7:  try:
           exif_data = extract_exif(img)
           gps_data = extract_gps(img)
         except:
           log error
           exif_data = None, gps_data = None
           metadata_failed = True

--- Thumbnail (non-fatal block) ---  
Step 8:  thumbnail_id = None
Step 9:  if ENABLE_THUMBNAIL:
           try:
             rotated = auto_rotate(img)
             thumb_buf = generate_thumbnail(rotated, DEFAULT_THUMB_SIZE)
             dataset = dl.datasets.get(dataset_id=item.datasetId, fetch=False)
             thumbnail_item = dataset.items.upload(
               local_path=thumb_buf,
               remote_path="/.dataloop/thumbnails",
               remote_name=f"{item.id}.png",
               overwrite=True,
               item_metadata={"system": {"originItemId": item.id}}
             )
             thumbnail_id = thumbnail_item.id
           except:
             log error
             thumbnail_failed = True

--- Build & write metadata ---
Step 10: meta = build_metadata(width, height, channels, thumbnail_id, exif_data, gps_data)
         NOTE: width/height come from Step 6 (original img.size, pre-rotation).
         Auto-rotate is applied ONLY inside the thumbnail pipeline.
         Metadata dimensions reflect raw pixel layout, not visual orientation.
Step 11: item.metadata.setdefault("system", {}).update(meta["system"])
         if "user" in meta:
           item.metadata.setdefault("user", {}).update(meta["user"])
Step 12: If metadata_failed:
           item.metadata["system"]["image-preprocess-fail"] = error_message
Step 13: item.update(system_metadata=True)

--- Final status ---
Step 14: If BOTH metadata and thumbnail failed → raise ValueError(...)
         (so FaaS execution is marked as failed)
```

#### Error Handling (per §5.7 exactly)

| Scenario | Behavior |
|----------|----------|
| Metadata extraction fails | Log error, set `metadata.system.image-preprocess-fail`, **still attempt thumbnail** |
| Thumbnail generation fails | Log error, **still save metadata** |
| Both fail | Raise `ValueError` so execution is marked failed |
| File too large | Skip processing entirely, log warning |
| Unsupported format (not image/*) | Skip processing, log warning |

**Key insight**: Metadata and thumbnail are **independent**. Either can fail without killing the other. Only when BOTH fail does the whole execution fail.

#### Key Differences from Current Code (B)

| Aspect | Current (B) | Target (C) |
|--------|-------------|------------|
| Download | To disk (`tmp/{itemId}/`) | To memory (`BytesIO`) |
| EXIF tool | Pillow `_getexif()` + exiftool CLI | Pillow `getexif()` + `get_ifd()` |
| EXIF fields | Orientation only | Full camera/capture/lens + whiteBalance |
| GPS storage | `system.location` + `user.location` | Same (keep dual for backward compat) |
| Thumbnail size | 128×128 | 128 longest edge (configurable) |
| Thumbnail format | JPEG for JPEG, PNG for rest | Always PNG |
| Thumbnail storage | Disk then upload | BytesIO then upload |
| TIFF handling | Skipped | Processed normally |
| Dimension cross-check | Pillow vs exiftool | Removed (Pillow is authoritative) |
| Temp cleanup | `shutil.rmtree` in `finally` | None needed (BytesIO, GC) |
| Config | Hardcoded | Env vars (§5.6) |
| Error model | Success booleans → aggregated raise | Independent try/except per concern |
| File size guard | None | MAX_FILE_SIZE_MB |

#### Tests (`test_integration.py`)

| # | Test | Setup | Assertions |
|---|------|-------|------------|
| 1 | Happy path — full EXIF JPEG | Mock item with JPEG buffer | `item.update` called, system has width/height/channels/thumbnailId/exif/location, user has location |
| 2 | No EXIF image (PNG) | Mock item with PNG buffer | system has width/height/channels/thumbnailId, no exif/location, no user.location |
| 3 | Non-image MIME | `mimetype: "video/mp4"` | Returns early, no download called |
| 4 | ENABLE_IMAGE_PREPROCESS=false | Env var set | Returns early, no download called |
| 5 | ENABLE_THUMBNAIL=false | Env var set | No thumbnail upload, no thumbnailId in system metadata |
| 6 | EXIF extraction fails | Mock `extract_exif` to raise | Thumbnail still generated, `image-preprocess-fail` set in system metadata |
| 7 | Thumbnail gen fails | Mock `generate_thumbnail` to raise | Metadata still written (without thumbnailId) |
| 8 | Both fail | Both mocked to raise | Raises `ValueError` |
| 9 | Download fails | Mock `item.download` to raise | Raises to caller |
| 10 | TIFF image | `mimetype: "image/tiff"` | Processed normally (not skipped) |
| 11 | Orientation — raw dimensions preserved | Portrait JPEG with orientation=6 (stored 800×600, tagged rotate-90) | `width`=800, `height`=600 in system metadata (original pre-rotation dimensions) |
| 12 | File too large | Item size > MAX_FILE_SIZE_MB | Returns early, log warning |
| 13 | GPS dual storage | JPEG with GPS | `system.location` AND `user.location` both populated |
| 14 | DEFAULT_THUMB_SIZE override | Env var set to 256 | Thumbnail fits 256×256 box |

---

### Phase 5: Infrastructure — Dockerfile, requirements.txt

#### `requirements.txt`

```
Pillow>=10.0.0
```

Note: `dtlpy` is provided by the Dataloop base image. We do NOT list it here to avoid version conflicts.

#### `Dockerfile`

```dockerfile
FROM gcr.io/viewo-g/piper/agent/runner/cpu/main:1.115.44.0

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY modules/ modules/
```

**Changes from current**:
- Remove `apt-get install -y exiftool`
- Remove `pip install PyExifTool==0.4.11`
- Add `requirements.txt` install
- Explicit COPY of only needed files (not `COPY . .` — exclude tests/docs from image)

#### `dataloop.json`

No changes to triggers, service config, or `on_create` function spec. The `test` function can be removed or kept — decision deferred.

---

### Phase 6: Cleanup & Verification

1. Delete `to_delete/` directory (if exists)
2. Evaluate for deletion: `application_deployment.py`, `infra.py`, `results/`, `build-docker.sh`, `dataloop_ford.json`, `dataloop_syngenta.json` — confirm with user
3. Remove old `modules/exif_utils.py` and `modules/image_utils.py`
4. Run full test suite — all green
5. Docker build test (if Docker available)
6. Update `.plans/initial-analysis.md` status to reflect completion

---

## 3. Implementation Order & Dependencies

```
Phase 0 (test infra)
    │
    ├──→ Phase 1 (exif_extractor) ──┐
    │                                ├──→ Phase 3 (metadata) ──→ Phase 4 (main.py)
    └──→ Phase 2 (thumbnail) ──────┘                               │
                                                              Phase 5 (Dockerfile)
                                                                   │
                                                              Phase 6 (cleanup)
```

**Each phase is a self-contained commit. Tests pass at each step.**

Recommended order:
1. Phase 0 — conftest + fixtures
2. Phase 1 — exif_extractor + tests
3. Phase 2 — thumbnail + tests
4. Phase 3 — metadata + tests
5. Phase 4 — main.py rewrite + integration tests
6. Phase 5 — Dockerfile + requirements.txt
7. Phase 6 — cleanup + final verification

---

## 4. Decisions & Assumptions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Pure Pillow, no `exifread` / `PyExifTool` | Pillow ≥10 has full `getexif()` + `get_ifd()` support. Single dependency. |
| D2 | `thumbnail()` not `resize()` | `thumbnail()` never upscales, preserves aspect ratio. Matches spec. |
| D3 | Auto-rotate ONLY in thumbnail pipeline; dimensions from original image | Width/height in metadata reflect raw pixel layout (pre-rotation). Auto-rotate is applied only when generating the thumbnail. |
| D4 | Open image once, pass `Image` object to modules | Single download + single Pillow open. No re-reading. `buffer.seek(0)` not even needed — `Image.open` is lazy; the object is reusable. |
| D5 | EXIF failure is non-fatal; thumbnail failure is non-fatal | Per §5.7. Only when BOTH fail → raise. |
| D6 | BytesIO everywhere — no disk I/O | Per §5.10. Removes cleanup, faster, no disk space concerns. |
| D7 | ExposureTime as string | Preserves precision. "1/8000" is more useful than 0.000125. |
| D8 | Pillow ≥ 10.0.0 minimum | Required for stable `getexif().get_ifd()`. Named constants (`Base`, `GPS`, `IFD`) available since ~9.2 but more reliable in 10+. |
| D9 | GPS dual storage (system + user) | Per §5.4 — backward compatibility. |
| D10 | Always PNG thumbnails | Per §5.5. Matches Rubiks (A). Simpler than format-switching. |
| D11 | Pre-rotation dims in metadata | `width`/`height` reflect the original raw pixel dimensions, not visual orientation. The original image is never rotated. |
| D12 | Env var config at module level | Simple, matches §5.6 names exactly. No config class needed. |
| D13 | No `aspectRatio` field | Per §5.3 — "No aspectRatio (Rubiks doesn't store it; keep metadata lean)." |
| D14 | `whiteBalance` included | Per §5.2 — present in Rubiks schema, added to extraction. |
| D15 | `image-preprocess-fail` marker on metadata failure | Per §5.7 — set in `metadata.system` so downstream can detect partial failures. |

---

## 5. Risks & Open Questions

| # | Risk / Question | Mitigation / Action |
|---|----------------|---------------------|
| R1 | `item.download(save_locally=False)` return type | Verify against dtlpy SDK. If returns file path string, need different approach. Test early in Phase 4. |
| R2 | `dataset.items.upload()` accepting BytesIO | Verify SDK supports buffer upload. If not, write to temp file + upload + delete. Test early in Phase 4. |
| R3 | `remote_name` parameter in `dataset.items.upload()` | Need to verify this controls the uploaded filename. May need `os.path.join` or different parameter. |
| R4 | Pillow can't read EXIF GPS IFD on some cameras | `get_ifd(IFD.GPSInfo)` may return empty dict on certain JPEGs. If found, add `exifread` as GPS-only fallback. |
| R5 | Large images (50+ MP) and memory | `MAX_IMAGE_PIXELS` env var guard. Pod RAM vs concurrency sizing is an ops concern. |
| R6 | HEIC/HEIF images | Out of scope (§7). Would need `pillow-heif`. |
| R7 | Multi-page TIFF | Out of scope (§7). Only first page processed (Pillow default). |
| R8 | Animated GIF/WEBP | Process first frame only. Document this. |
| R9 | `item.set_thumbnail()` vs `thumbnailId` | Current code sets `item.metadata['system']['thumbnailId']`. Verify this is sufficient or if `set_thumbnail()` API call is also needed. |
| R10 | File size — how to check before download | Need `item.metadata['system']['size']` or similar. If not available pre-download, check buffer length after download. |
| R11 | Pillow `Base.DateTimeOriginal` — is it in main IFD or ExifIFD? | In the §5.9 example code, `DateTimeOriginal` is accessed from main `exif` object, but it actually lives in ExifIFD (tag 36867). Need to verify Pillow's `Base.DateTimeOriginal` works with `exif.get()` vs `exif_ifd.get()`. Test in Phase 1. |

---

## 6. Verification Checklist (Definition of Done)

- [ ] All modules created with public APIs matching this plan
- [ ] All unit tests pass (Phases 0-3)
- [ ] Integration tests pass (Phase 4)
- [ ] `main.py` follows pipeline exactly
- [ ] EXIF schema matches §5.2 (including `whiteBalance`)
- [ ] System metadata matches §5.3 (no `aspectRatio`)
- [ ] GPS dual storage: `system.location` + `user.location` (§5.4)
- [ ] Thumbnail matches §5.5 (512 PNG, no upscale, auto-rotate, `{itemId}.png`)
- [ ] Config env vars match §5.6 names exactly
- [ ] Error handling matches §5.7 (independent failures, both-fail raises)
- [ ] No exiftool dependency (Dockerfile clean, no PyExifTool)
- [ ] No disk I/O for source file (BytesIO only)
- [ ] TIFF images processed (not skipped)
- [ ] Docker builds successfully
- [ ] All legacy files evaluated for deletion
