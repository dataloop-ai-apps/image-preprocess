import os
import sys
import pytest
from io import BytesIO
from unittest.mock import MagicMock
from PIL import Image
from PIL.ExifTags import Base, GPS, IFD
from PIL.TiffImagePlugin import IFDRational

# Add img-preprocess dir to sys.path so tests can import the source modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'img-preprocess'))


def create_test_image(width, height, mode="RGB", exif=None, gps=None):
    """Programmatically creates a Pillow Image with optional EXIF data baked in.
    
    Returns a BytesIO buffer containing the saved JPEG/PNG.
    """
    img = Image.new(mode, (width, height))
    
    if exif or gps:
        exif_obj = img.getexif()
        
        # Add main IFD tags
        if exif:
            for tag, value in exif.items():
                exif_obj[tag] = value
        
        # Add GPS IFD tags
        if gps:
            gps_ifd = {}
            for tag, value in gps.items():
                gps_ifd[tag] = value
            exif_obj[IFD.GPSInfo] = gps_ifd
        
        # Convert to bytes
        exif_bytes = exif_obj.tobytes()
        
        # Save with EXIF
        buf = BytesIO()
        img.save(buf, format="JPEG", exif=exif_bytes)
        buf.seek(0)
        return buf
    
    # Save without EXIF
    buf = BytesIO()
    if mode in ("RGBA", "LA"):
        img.save(buf, format="PNG")
    else:
        img.save(buf, format="JPEG")
    buf.seek(0)
    return buf


@pytest.fixture
def landscape_jpeg():
    """800×600 JPEG, full EXIF (make, model, ISO, aperture, exposure, focal, lens, flash, whiteBalance, orientation=1, GPS)"""
    exif = {
        Base.Orientation: 1,
        Base.Make: "Apple",
        Base.Model: "iPhone 15 Pro",
        Base.DateTimeOriginal: "2024:01:15 10:30:45",
    }
    
    # ExifIFD tags - use IFDRational for rational values
    exif_ifd = {
        Base.ISOSpeedRatings: 100,
        Base.FNumber: IFDRational(9, 5),  # 1.78
        Base.ExposureTime: IFDRational(1, 120),
        Base.FocalLength: IFDRational(6765, 1000),  # 6.765
        Base.FocalLengthIn35mmFilm: 24,
        Base.LensModel: "iPhone 15 Pro back camera 6.765mm f/1.78",
        Base.Flash: 0,
        Base.WhiteBalance: 0,
    }
    
    # GPS tags - use IFDRational for rational values
    gps = {
        GPS.GPSLatitudeRef: "N",
        GPS.GPSLatitude: [IFDRational(32, 1), IFDRational(5, 1), IFDRational(7, 1)],  # 32°5'7"
        GPS.GPSLongitudeRef: "E",
        GPS.GPSLongitude: [IFDRational(34, 1), IFDRational(46, 1), IFDRational(55, 1)],  # 34°46'55"
        GPS.GPSAltitudeRef: 0,
        GPS.GPSAltitude: IFDRational(15, 1),  # 15 meters
    }
    
    img = Image.new("RGB", (800, 600))
    exif_obj = img.getexif()
    
    for tag, value in exif.items():
        exif_obj[tag] = value
    
    exif_obj[IFD.Exif] = exif_ifd
    exif_obj[IFD.GPSInfo] = gps
    
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif_obj.tobytes())
    buf.seek(0)
    return buf


@pytest.fixture
def portrait_rotated_jpeg():
    """600×800 JPEG but saved as 800×600 with orientation=6 (90° CW)"""
    exif = {
        Base.Orientation: 6,
        Base.Make: "Apple",
        Base.Model: "iPhone 15 Pro",
    }
    
    img = Image.new("RGB", (800, 600))
    exif_obj = img.getexif()
    
    for tag, value in exif.items():
        exif_obj[tag] = value
    
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif_obj.tobytes())
    buf.seek(0)
    return buf


@pytest.fixture
def no_exif_png():
    """400×300 PNG, no EXIF at all"""
    img = Image.new("RGB", (400, 300))
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


@pytest.fixture
def small_jpeg():
    """100×80 JPEG, minimal EXIF (orientation only)"""
    exif = {
        Base.Orientation: 1,
    }
    
    img = Image.new("RGB", (100, 80))
    exif_obj = img.getexif()
    
    for tag, value in exif.items():
        exif_obj[tag] = value
    
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif_obj.tobytes())
    buf.seek(0)
    return buf


@pytest.fixture
def rgba_png():
    """400×300 RGBA PNG"""
    img = Image.new("RGBA", (400, 300), (255, 0, 0, 128))
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


@pytest.fixture
def tiff_image():
    """400×300 TIFF (single page)"""
    img = Image.new("RGB", (400, 300))
    buf = BytesIO()
    img.save(buf, format="TIFF")
    buf.seek(0)
    return buf


@pytest.fixture
def mock_dl_item():
    """Factory fixture that creates a MagicMock mimicking dl.Item"""
    def _mock_item(item_id="test-item-id", name="test.jpg", mimetype="image/jpeg", buffer=None):
        item = MagicMock()
        item.id = item_id
        item.name = name
        item.datasetId = "test-dataset-id"
        item.metadata = {"system": {"mimetype": mimetype}, "user": {}}
        
        if buffer is None:
            # Default empty buffer
            buffer = BytesIO()
            Image.new("RGB", (100, 100)).save(buffer, format="JPEG")
            buffer.seek(0)
        
        item.download.return_value = buffer
        item.update = MagicMock(return_value=item)
        return item
    
    return _mock_item


@pytest.fixture
def mock_dl_progress():
    """Mock with .logger attribute"""
    progress = MagicMock()
    progress.logger = MagicMock()
    progress.logger.info = MagicMock()
    progress.logger.warning = MagicMock()
    progress.logger.error = MagicMock()
    progress.logger.exception = MagicMock()
    return progress


@pytest.fixture
def mock_dataset():
    """Mock for dl.datasets.get() → .items.upload() returns a mock thumbnail item with .id"""
    dataset = MagicMock()
    thumbnail_item = MagicMock()
    thumbnail_item.id = "thumbnail-abc123"
    dataset.items.upload.return_value = thumbnail_item
    return dataset
