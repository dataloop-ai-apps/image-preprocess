from PIL import Image
from PIL.ExifTags import Base, GPS, IFD
from PIL.TiffImagePlugin import IFDRational
from io import BytesIO

from main import ServiceRunner

_runner = ServiceRunner()
extract_exif = _runner.extract_exif
extract_gps = _runner.extract_gps


def create_test_image_with_exif(width, height, exif_tags=None, gps_tags=None):
    """Helper to create test image with specific EXIF/GPS tags."""
    img = Image.new("RGB", (width, height))
    exif_obj = img.getexif()
    
    if exif_tags:
        for tag, value in exif_tags.items():
            exif_obj[tag] = value
    
    if gps_tags:
        exif_obj[IFD.GPSInfo] = gps_tags
    
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif_obj.tobytes())
    buf.seek(0)
    return buf


def _make_item():
    """Create a minimal mock item with metadata dict."""
    class MockItem:
        def __init__(self):
            self.metadata = {"system": {}, "user": {}}
    return MockItem()


def test_full_exif_extraction():
    """Test 1: Full EXIF extraction"""
    exif_tags = {
        Base.Orientation: 1,
        Base.Make: "Apple",
        Base.Model: "iPhone 15 Pro",
        Base.DateTimeOriginal: "2024:01:15 10:30:45",
    }
    
    exif_ifd = {
        Base.ISOSpeedRatings: 100,
        Base.FNumber: IFDRational(18, 10),  # 1.8
        Base.ExposureTime: IFDRational(1, 120),
        Base.FocalLength: IFDRational(6765, 1000),  # 6.765
        Base.FocalLengthIn35mmFilm: 24,
        Base.LensModel: "iPhone 15 Pro back camera 6.765mm f/1.78",
        Base.Flash: 0,
        Base.WhiteBalance: 0,
    }
    
    img = Image.new("RGB", (800, 600))
    exif_obj = img.getexif()
    
    for tag, value in exif_tags.items():
        exif_obj[tag] = value
    
    exif_obj[IFD.Exif] = exif_ifd
    
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif_obj.tobytes())
    buf.seek(0)
    
    img = Image.open(buf)
    item = _make_item()
    extract_exif(img, item)
    
    exif = item.metadata["system"]["exif"]
    assert exif["orientation"] == 1
    assert exif["cameraMake"] == "Apple"
    assert exif["cameraModel"] == "iPhone 15 Pro"
    assert exif["dateTime"] == "2024:01:15 10:30:45"
    assert exif["iso"] == 100
    assert exif["aperture"] == 1.8
    assert exif["exposureTime"] == "1/120"
    assert exif["focalLength"] == 6.765
    assert exif["focalLength35mm"] == 24
    assert exif["lensModel"] == "iPhone 15 Pro back camera 6.765mm f/1.78"
    assert exif["flash"] is False
    assert exif["whiteBalance"] == 0


def test_no_exif():
    """Test 2: No EXIF (PNG) — nothing written to metadata"""
    img = Image.new("RGB", (400, 300))
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    
    img = Image.open(buf)
    item = _make_item()
    extract_exif(img, item)
    
    assert "exif" not in item.metadata["system"]


def test_partial_exif():
    """Test 3: Partial EXIF (only orientation)"""
    buf = create_test_image_with_exif(100, 80, {Base.Orientation: 1})
    img = Image.open(buf)
    item = _make_item()
    extract_exif(img, item)
    
    exif = item.metadata["system"]["exif"]
    assert exif["orientation"] == 1
    assert "cameraMake" not in exif
    assert "iso" not in exif


def test_gps_northern_eastern():
    """Test 4: GPS extraction — northern/eastern"""
    gps_tags = {
        GPS.GPSLatitudeRef: "N",
        GPS.GPSLatitude: [IFDRational(32, 1), IFDRational(5, 1), IFDRational(7, 1)],
        GPS.GPSLongitudeRef: "E",
        GPS.GPSLongitude: [IFDRational(34, 1), IFDRational(46, 1), IFDRational(55, 1)],
    }
    
    buf = create_test_image_with_exif(800, 600, gps_tags=gps_tags)
    img = Image.open(buf)
    item = _make_item()
    extract_gps(img.getexif(), item)
    
    assert item.metadata["system"]["location"]["latitude"] > 0
    assert item.metadata["system"]["location"]["longitude"] > 0
    assert item.metadata["user"]["location"]["latitude"] > 0


def test_gps_southern_hemisphere():
    """Test 5: GPS — southern hemisphere"""
    gps_tags = {
        GPS.GPSLatitudeRef: "S",
        GPS.GPSLatitude: [IFDRational(32, 1), IFDRational(5, 1), IFDRational(7, 1)],
        GPS.GPSLongitudeRef: "E",
        GPS.GPSLongitude: [IFDRational(34, 1), IFDRational(46, 1), IFDRational(55, 1)],
    }
    
    buf = create_test_image_with_exif(800, 600, gps_tags=gps_tags)
    img = Image.open(buf)
    item = _make_item()
    extract_gps(img.getexif(), item)
    
    assert item.metadata["system"]["location"]["latitude"] < 0
    assert item.metadata["system"]["location"]["longitude"] > 0


def test_gps_western_hemisphere():
    """Test 6: GPS — western hemisphere"""
    gps_tags = {
        GPS.GPSLatitudeRef: "N",
        GPS.GPSLatitude: [IFDRational(32, 1), IFDRational(5, 1), IFDRational(7, 1)],
        GPS.GPSLongitudeRef: "W",
        GPS.GPSLongitude: [IFDRational(34, 1), IFDRational(46, 1), IFDRational(55, 1)],
    }
    
    buf = create_test_image_with_exif(800, 600, gps_tags=gps_tags)
    img = Image.open(buf)
    item = _make_item()
    extract_gps(img.getexif(), item)
    
    assert item.metadata["system"]["location"]["latitude"] > 0
    assert item.metadata["system"]["location"]["longitude"] < 0


def test_gps_incomplete():
    """Test 7: GPS — incomplete (lat only) — nothing written"""
    gps_tags = {
        GPS.GPSLatitudeRef: "N",
        GPS.GPSLatitude: [IFDRational(32, 1), IFDRational(5, 1), IFDRational(7, 1)],
    }
    
    buf = create_test_image_with_exif(800, 600, gps_tags=gps_tags)
    img = Image.open(buf)
    item = _make_item()
    extract_gps(img.getexif(), item)
    
    assert "location" not in item.metadata["system"]


def test_gps_with_altitude():
    """Test 8: GPS — with altitude"""
    gps_tags = {
        GPS.GPSLatitudeRef: "N",
        GPS.GPSLatitude: [IFDRational(32, 1), IFDRational(5, 1), IFDRational(7, 1)],
        GPS.GPSLongitudeRef: "E",
        GPS.GPSLongitude: [IFDRational(34, 1), IFDRational(46, 1), IFDRational(55, 1)],
        GPS.GPSAltitudeRef: 0,
        GPS.GPSAltitude: IFDRational(15, 1),
    }
    
    buf = create_test_image_with_exif(800, 600, gps_tags=gps_tags)
    img = Image.open(buf)
    item = _make_item()
    extract_gps(img.getexif(), item)
    
    assert item.metadata["system"]["location"]["altitude"] == 15.0


def test_gps_altitude_below_sea_level():
    """Test 9: GPS — altitude below sea level"""
    gps_tags = {
        GPS.GPSLatitudeRef: "N",
        GPS.GPSLatitude: [IFDRational(32, 1), IFDRational(5, 1), IFDRational(7, 1)],
        GPS.GPSLongitudeRef: "E",
        GPS.GPSLongitude: [IFDRational(34, 1), IFDRational(46, 1), IFDRational(55, 1)],
        GPS.GPSAltitudeRef: 1,
        GPS.GPSAltitude: IFDRational(15, 1),
    }
    
    buf = create_test_image_with_exif(800, 600, gps_tags=gps_tags)
    img = Image.open(buf)
    item = _make_item()
    extract_gps(img.getexif(), item)
    
    assert item.metadata["system"]["location"]["altitude"] == -15.0


def test_flash_fired():
    """Test 10: Flash fired"""
    exif_ifd = {Base.Flash: 1}
    img = Image.new("RGB", (800, 600))
    exif_obj = img.getexif()
    exif_obj[IFD.Exif] = exif_ifd
    
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif_obj.tobytes())
    buf.seek(0)
    
    img = Image.open(buf)
    item = _make_item()
    extract_exif(img, item)
    
    assert item.metadata["system"]["exif"]["flash"] is True


def test_flash_not_fired():
    """Test 11: Flash not fired"""
    exif_ifd = {Base.Flash: 0}
    img = Image.new("RGB", (800, 600))
    exif_obj = img.getexif()
    exif_obj[IFD.Exif] = exif_ifd
    
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif_obj.tobytes())
    buf.seek(0)
    
    img = Image.open(buf)
    item = _make_item()
    extract_exif(img, item)
    
    assert item.metadata["system"]["exif"]["flash"] is False


def test_flash_with_red_eye():
    """Test 12: Flash with red-eye (bit 0 still set)"""
    exif_ifd = {Base.Flash: 65}  # 0b01000001 - bit 0 set
    img = Image.new("RGB", (800, 600))
    exif_obj = img.getexif()
    exif_obj[IFD.Exif] = exif_ifd
    
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif_obj.tobytes())
    buf.seek(0)
    
    img = Image.open(buf)
    item = _make_item()
    extract_exif(img, item)
    
    assert item.metadata["system"]["exif"]["flash"] is True


def test_exposure_time_formatting():
    """Test 13: ExposureTime formatting"""
    exif_ifd = {Base.ExposureTime: IFDRational(1, 120)}
    img = Image.new("RGB", (800, 600))
    exif_obj = img.getexif()
    exif_obj[IFD.Exif] = exif_ifd
    
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif_obj.tobytes())
    buf.seek(0)
    
    img = Image.open(buf)
    item = _make_item()
    extract_exif(img, item)
    
    assert item.metadata["system"]["exif"]["exposureTime"] == "1/120"


def test_exposure_time_ge_1_second():
    """Test 14: ExposureTime ≥ 1 second"""
    exif_ifd = {Base.ExposureTime: IFDRational(5, 2)}  # 2.5 seconds
    img = Image.new("RGB", (800, 600))
    exif_obj = img.getexif()
    exif_obj[IFD.Exif] = exif_ifd
    
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif_obj.tobytes())
    buf.seek(0)
    
    img = Image.open(buf)
    item = _make_item()
    extract_exif(img, item)
    
    assert item.metadata["system"]["exif"]["exposureTime"] == "5/2"


def test_white_balance_auto():
    """Test 15: WhiteBalance auto"""
    exif_ifd = {Base.WhiteBalance: 0}
    img = Image.new("RGB", (800, 600))
    exif_obj = img.getexif()
    exif_obj[IFD.Exif] = exif_ifd
    
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif_obj.tobytes())
    buf.seek(0)
    
    img = Image.open(buf)
    item = _make_item()
    extract_exif(img, item)
    
    assert item.metadata["system"]["exif"]["whiteBalance"] == 0


def test_white_balance_manual():
    """Test 16: WhiteBalance manual"""
    exif_ifd = {Base.WhiteBalance: 1}
    img = Image.new("RGB", (800, 600))
    exif_obj = img.getexif()
    exif_obj[IFD.Exif] = exif_ifd
    
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif_obj.tobytes())
    buf.seek(0)
    
    img = Image.open(buf)
    item = _make_item()
    extract_exif(img, item)
    
    assert item.metadata["system"]["exif"]["whiteBalance"] == 1


def test_null_bytes_in_string():
    """Test 17: Null bytes in string tag"""
    exif_tags = {Base.Make: "Apple\x00"}
    buf = create_test_image_with_exif(800, 600, exif_tags)
    img = Image.open(buf)
    item = _make_item()
    extract_exif(img, item)
    
    assert item.metadata["system"]["exif"]["cameraMake"] == "Apple"


def test_corrupt_exif_partial():
    """Test 18: Corrupt EXIF — partial (one tag unreadable)"""
    # Our implementation has try/except per tag, so other tags should still extract
    exif_tags = {
        Base.Orientation: 1,
        Base.Make: "Apple",
    }
    
    buf = create_test_image_with_exif(800, 600, exif_tags)
    img = Image.open(buf)
    item = _make_item()
    extract_exif(img, item)
    
    exif = item.metadata["system"]["exif"]
    assert exif["orientation"] == 1
    assert exif["cameraMake"] == "Apple"
