
# Initial Analysis — image-preprocess

## Repository State
- **Not** a FastAPI app — this is a **Dataloop FaaS service** (`dl.BaseServiceRunner`)
- Single entry point: `main.py` → `ServiceRunner.on_create(item, progress)`
- Triggered on `Item.Created` / `Item.Clone` for images where `etl.failed == true`
- Dependencies: `Pillow`, `PyExifTool` (+ system `exiftool` binary), `dtlpy`
- Docker image: `gcr.io/viewo-g/piper/agent/cpu/image-preprocess:5`

## Current Behavior
1. Downloads item to `tmp/{itemId}/`
2. Extracts metadata via Pillow: width, height, channels, orientation, GPS
3. Cross-checks dimensions via exiftool CLI
4. Generates 128×128 thumbnail (JPEG for JPEG, PNG for others)
5. Uploads thumbnail to `/.dataloop/thumbnails/{itemId}.{ext}`
6. Sets `metadata.system.{exif, width, height, channels, thumbnailId, location}`
7. Also sets `metadata.user.location` (GPS duplicate)
8. Updates item, cleans up temp folder

## Completed
- [x] Full code analysis of current Python implementation
- [x] **Behavior comparison document** — `docs/behavior-comparison.md`
  - Three-way comparison: Rubiks vs Current Python vs Target
  - 9 gaps identified (G1–G9)
  - Merged target specification with exact metadata schemas
  - 8-phase implementation plan

## Key Gaps Found
- G1: Camera/capture EXIF metadata not extracted (only Orientation)
- G2: Thumbnail 128×128 instead of 512×512
- G3: TIFF thumbnails skipped (intentional?)
- G5: Heavy exiftool CLI dependency just for dimension cross-check
- G7: No configurable feature flags
- G8: Uses deprecated `_getexif()` API

## Next Steps
1. Remove exiftool dependency; use Pillow's `getexif()` + `get_ifd()` for all EXIF
2. Extract full EXIF (camera, capture, lens) into structured metadata
3. Change thumbnail default to 512×512
4. Add env var configuration
5. Update Dockerfile
6. Add tests
