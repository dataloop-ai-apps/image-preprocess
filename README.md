# Image Preprocess

Dataloop system app for image processing on upload. Extracts EXIF/GPS metadata, generates thumbnails, and converts TIFF to PNG.

## Modules

- **img-preprocess**: Standard image preprocessing (EXIF/GPS extraction, thumbnail generation)
- **tiff-preprocess**: TIFF to PNG conversion with geospatial metadata support

## Structure

```
img-preprocess/        # Standard image processing
  main.py              # ServiceRunner: EXIF/GPS extraction + thumbnail generation
tiff-preprocess/       # TIFF conversion
  main.py              # ServiceRunner: TIFF to PNG conversion + metadata + thumbnail
common/                # Shared utilities
  etl_errors.py        # ETL error recording helper
tests/                 # pytest suite (targets img-preprocess)
```

Each `main.py` is self-contained: EXIF/GPS extraction and thumbnail generation
live as methods on the module's `ServiceRunner` rather than in separate modules.

## Run Tests

The runtime image already provides GDAL, rasterio, and dtlpy. For local
testing, install the development dependencies (which avoid the GDAL/rasterio
build step) and run pytest:

```bash
pip install -r requirements-dev.txt
pytest tests/
```