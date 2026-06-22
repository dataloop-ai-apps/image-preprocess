# Test Fixtures

This directory contains test fixtures for the image-preprocess project.

## Fixture Generation

Test images are programmatically generated in `tests/conftest.py` using the `create_test_image()` function. This function creates Pillow Images with optional EXIF data baked in, then saves them to BytesIO buffers for use in tests.

## Available Fixtures

- `landscape_jpeg`: 800×600 JPEG with full EXIF (make, model, ISO, aperture, exposure, focal, lens, flash, whiteBalance, orientation=1, GPS)
- `portrait_rotated_jpeg`: 600×800 JPEG saved as 800×600 with orientation=6 (90° CW)
- `no_exif_png`: 400×300 PNG with no EXIF
- `small_jpeg`: 100×80 JPEG with minimal EXIF (orientation only)
- `rgba_png`: 400×300 RGBA PNG
- `tiff_image`: 400×300 TIFF (single page)

## Mock Fixtures

- `mock_dl_item`: Factory fixture that creates a MagicMock mimicking `dl.Item`
- `mock_dl_progress`: Mock with `.logger` attribute
- `mock_dataset`: Mock for `dl.datasets.get()` → `.items.upload()` returns a mock thumbnail item
