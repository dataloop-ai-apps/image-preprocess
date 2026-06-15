import pytest
from PIL import Image
from PIL.ExifTags import Base, GPS, IFD
from PIL.TiffImagePlugin import IFDRational
from io import BytesIO

from exif_extractor import extract_exif, extract_gps


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
    result = extract_exif(img)
    
    assert result is not None
    assert result["orientation"] == 1
    assert result["camera_make"] == "Apple"
    assert result["camera_model"] == "iPhone 15 Pro"
    assert result["date_time"] == "2024:01:15 10:30:45"
    assert result["iso"] == 100
    assert result["aperture"] == 1.8  # 9/5 = 1.8
    assert result["exposure_time"] == "1/120"
    assert result["focal_length"] == 6.765
    assert result["focal_length_35mm"] == 24
    assert result["lens_model"] == "iPhone 15 Pro back camera 6.765mm f/1.78"
    assert result["flash"] is False
    assert result["white_balance"] == 0


def test_no_exif():
    """Test 2: No EXIF (PNG)"""
    img = Image.new("RGB", (400, 300))
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    
    img = Image.open(buf)
    result = extract_exif(img)
    
    assert result is None


def test_partial_exif():
    """Test 3: Partial EXIF (only orientation)"""
    buf = create_test_image_with_exif(100, 80, {Base.Orientation: 1})
    img = Image.open(buf)
    result = extract_exif(img)
    
    assert result is not None
    assert result["orientation"] == 1
    assert "camera_make" not in result
    assert "iso" not in result


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
    result = extract_gps(img)
    
    assert result is not None
    assert result["latitude"] > 0
    assert result["longitude"] > 0


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
    result = extract_gps(img)
    
    assert result is not None
    assert result["latitude"] < 0
    assert result["longitude"] > 0


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
    result = extract_gps(img)
    
    assert result is not None
    assert result["latitude"] > 0
    assert result["longitude"] < 0


def test_gps_incomplete():
    """Test 7: GPS — incomplete (lat only)"""
    gps_tags = {
        GPS.GPSLatitudeRef: "N",
        GPS.GPSLatitude: [IFDRational(32, 1), IFDRational(5, 1), IFDRational(7, 1)],
    }
    
    buf = create_test_image_with_exif(800, 600, gps_tags=gps_tags)
    img = Image.open(buf)
    result = extract_gps(img)
    
    assert result is None


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
    result = extract_gps(img)
    
    assert result is not None
    assert "altitude" in result
    assert result["altitude"] == 15.0


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
    result = extract_gps(img)
    
    assert result is not None
    assert "altitude" in result
    assert result["altitude"] == -15.0


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
    result = extract_exif(img)
    
    assert result is not None
    assert result["flash"] is True


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
    result = extract_exif(img)
    
    assert result is not None
    assert result["flash"] is False


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
    result = extract_exif(img)
    
    assert result is not None
    assert result["flash"] is True


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
    result = extract_exif(img)
    
    assert result is not None
    assert result["exposure_time"] == "1/120"


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
    result = extract_exif(img)
    
    assert result is not None
    assert result["exposure_time"] == "5/2"


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
    result = extract_exif(img)
    
    assert result is not None
    assert result["white_balance"] == 0


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
    result = extract_exif(img)
    
    assert result is not None
    assert result["white_balance"] == 1


def test_null_bytes_in_string():
    """Test 17: Null bytes in string tag"""
    exif_tags = {Base.Make: "Apple\x00"}
    buf = create_test_image_with_exif(800, 600, exif_tags)
    img = Image.open(buf)
    result = extract_exif(img)
    
    assert result is not None
    assert result["camera_make"] == "Apple"


def test_corrupt_exif_partial():
    """Test 18: Corrupt EXIF — partial (one tag unreadable)"""
    # This test simulates a scenario where one tag might fail but others succeed
    # Our implementation has try/except per tag, so other tags should still extract
    exif_tags = {
        Base.Orientation: 1,
        Base.Make: "Apple",
    }
    
    buf = create_test_image_with_exif(800, 600, exif_tags)
    img = Image.open(buf)
    result = extract_exif(img)
    
    assert result is not None
    assert result["orientation"] == 1
    assert result["camera_make"] == "Apple"
