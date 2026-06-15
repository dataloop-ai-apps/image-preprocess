# Image Preprocess

Dataloop system app that runs on every image upload — extracts EXIF/GPS metadata, generates a thumbnail, and writes everything back to the item.

## Structure

```
img-preprocess/     # all source code
  main.py           # ServiceRunner entry point
  exif_extractor.py # EXIF & GPS extraction
  thumbnail.py      # auto-rotate + thumbnail generation
  metadata.py       # metadata dict builder
tests/              # pytest suite
```

## Run Tests

```bash
pip install -r requirements.txt
pytest tests/
```