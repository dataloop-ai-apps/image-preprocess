# Image Preprocess

Dataloop system app for image processing on upload. Extracts EXIF/GPS metadata, generates thumbnails, and converts TIFF to PNG.

## Modules

- **img-preprocess**: Standard image preprocessing (EXIF/GPS extraction, thumbnail generation)
- **tiff-preprocess**: TIFF to PNG conversion with geospatial metadata support

## Structure

```
img-preprocess/         # Standard image processing
  main.py              # ServiceRunner entry point
  metadata_extractor.py # EXIF & GPS extraction
  thumbnail.py         # Thumbnail generation
tiff-preprocess/       # TIFF conversion
  main.py              # TIFF to PNG converter
common/                # Shared utilities
  etl_errors.py        # ETL error recording
tests/                 # pytest suite
```

## Run Tests

```bash
pip install -r requirements.txt
pytest tests/
```