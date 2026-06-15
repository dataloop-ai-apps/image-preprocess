import pytest

from metadata import build_metadata


def test_full_data():
    """Test 1: Full data"""
    exif_data = {
        "orientation": 1,
        "camera_make": "Apple",
        "camera_model": "iPhone 15 Pro",
        "date_time": "2024:01:15 10:30:45",
        "iso": 100,
        "aperture": 1.78,
        "exposure_time": "1/120",
        "focal_length": 6.765,
        "focal_length_35mm": 24,
        "lens_model": "iPhone 15 Pro back camera 6.765mm f/1.78",
        "flash": False,
        "white_balance": 0,
    }
    
    gps_data = {
        "latitude": 32.0853,
        "longitude": 34.7818,
        "altitude": 15.0,
    }
    
    result = build_metadata(4032, 3024, 3, "abc123", exif_data, gps_data)
    
    assert "system" in result
    assert "user" in result
    assert result["system"]["width"] == 4032
    assert result["system"]["height"] == 3024
    assert result["system"]["channels"] == 3
    assert result["system"]["thumbnailId"] == "abc123"
    assert "exif" in result["system"]
    assert result["system"]["exif"]["orientation"] == 1
    assert result["system"]["exif"]["cameraMake"] == "Apple"
    assert result["system"]["exif"]["cameraModel"] == "iPhone 15 Pro"
    assert result["system"]["exif"]["dateTime"] == "2024:01:15 10:30:45"
    assert result["system"]["exif"]["iso"] == 100
    assert result["system"]["exif"]["aperture"] == 1.78
    assert result["system"]["exif"]["exposureTime"] == "1/120"
    assert result["system"]["exif"]["focalLength"] == 6.765
    assert result["system"]["exif"]["focalLength35mm"] == 24
    assert result["system"]["exif"]["lensModel"] == "iPhone 15 Pro back camera 6.765mm f/1.78"
    assert result["system"]["exif"]["flash"] is False
    assert result["system"]["exif"]["whiteBalance"] == 0
    assert "location" in result["system"]
    assert result["system"]["location"]["latitude"] == 32.0853
    assert result["system"]["location"]["longitude"] == 34.7818
    assert result["system"]["location"]["altitude"] == 15.0
    assert result["user"]["location"]["latitude"] == 32.0853
    assert result["user"]["location"]["longitude"] == 34.7818
    assert result["user"]["location"]["altitude"] == 15.0


def test_no_exif_no_gps():
    """Test 2: No EXIF, no GPS"""
    result = build_metadata(4032, 3024, 3, "abc123", None, None)
    
    assert "system" in result
    assert "user" not in result
    assert result["system"]["width"] == 4032
    assert result["system"]["height"] == 3024
    assert result["system"]["channels"] == 3
    assert result["system"]["thumbnailId"] == "abc123"
    assert "exif" not in result["system"]
    assert "location" not in result["system"]


def test_exif_but_no_gps():
    """Test 3: EXIF but no GPS"""
    exif_data = {
        "orientation": 1,
        "iso": 100,
    }
    
    result = build_metadata(4032, 3024, 3, "abc123", exif_data, None)
    
    assert "system" in result
    assert "user" not in result
    assert "exif" in result["system"]
    assert result["system"]["exif"]["orientation"] == 1
    assert result["system"]["exif"]["iso"] == 100
    assert "location" not in result["system"]


def test_gps_but_no_exif():
    """Test 4: GPS but no EXIF"""
    gps_data = {
        "latitude": 32.0853,
        "longitude": 34.7818,
    }
    
    result = build_metadata(4032, 3024, 3, "abc123", None, gps_data)
    
    assert "system" in result
    assert "user" in result
    assert "exif" not in result["system"]
    assert "location" in result["system"]
    assert result["system"]["location"]["latitude"] == 32.0853
    assert result["system"]["location"]["longitude"] == 34.7818
    assert result["user"]["location"]["latitude"] == 32.0853
    assert result["user"]["location"]["longitude"] == 34.7818


def test_partial_exif():
    """Test 5: Partial EXIF"""
    exif_data = {
        "orientation": 1,
        "iso": 100,
    }
    
    result = build_metadata(4032, 3024, 3, "abc123", exif_data, None)
    
    assert "exif" in result["system"]
    assert result["system"]["exif"]["orientation"] == 1
    assert result["system"]["exif"]["iso"] == 100
    assert "cameraMake" not in result["system"]["exif"]


def test_empty_exif_dict():
    """Test 6: Empty EXIF dict"""
    result = build_metadata(4032, 3024, 3, "abc123", {}, None)
    
    assert "exif" not in result["system"]


def test_gps_with_altitude():
    """Test 7: GPS with altitude"""
    gps_data = {
        "latitude": 32.0853,
        "longitude": 34.7818,
        "altitude": 15.0,
    }
    
    result = build_metadata(4032, 3024, 3, "abc123", None, gps_data)
    
    assert "altitude" in result["system"]["location"]
    assert result["system"]["location"]["altitude"] == 15.0
    assert "altitude" in result["user"]["location"]
    assert result["user"]["location"]["altitude"] == 15.0


def test_gps_without_altitude():
    """Test 8: GPS without altitude"""
    gps_data = {
        "latitude": 32.0853,
        "longitude": 34.7818,
    }
    
    result = build_metadata(4032, 3024, 3, "abc123", None, gps_data)
    
    assert "altitude" not in result["system"]["location"]
    assert "altitude" not in result["user"]["location"]


def test_key_mapping_correctness():
    """Test 9: Key mapping correctness"""
    exif_data = {
        "orientation": 1,
        "camera_make": "Apple",
        "camera_model": "iPhone 15 Pro",
        "date_time": "2024:01:15 10:30:45",
        "iso": 100,
        "aperture": 1.78,
        "exposure_time": "1/120",
        "focal_length": 6.765,
        "focal_length_35mm": 24,
        "lens_model": "iPhone 15 Pro back camera 6.765mm f/1.78",
        "flash": False,
        "white_balance": 0,
    }
    
    result = build_metadata(4032, 3024, 3, "abc123", exif_data, None)
    
    assert "orientation" in result["system"]["exif"]
    assert "cameraMake" in result["system"]["exif"]
    assert "cameraModel" in result["system"]["exif"]
    assert "dateTime" in result["system"]["exif"]
    assert "iso" in result["system"]["exif"]
    assert "aperture" in result["system"]["exif"]
    assert "exposureTime" in result["system"]["exif"]
    assert "focalLength" in result["system"]["exif"]
    assert "focalLength35mm" in result["system"]["exif"]
    assert "lensModel" in result["system"]["exif"]
    assert "flash" in result["system"]["exif"]
    assert "whiteBalance" in result["system"]["exif"]
    
    # Ensure snake_case keys are NOT present
    assert "camera_make" not in result["system"]["exif"]
    assert "camera_model" not in result["system"]["exif"]
    assert "date_time" not in result["system"]["exif"]
    assert "exposure_time" not in result["system"]["exif"]
    assert "focal_length" not in result["system"]["exif"]
    assert "focal_length_35mm" not in result["system"]["exif"]
    assert "lens_model" not in result["system"]["exif"]
    assert "white_balance" not in result["system"]["exif"]


def test_no_thumbnail_id():
    """Test 10: No thumbnailId"""
    result = build_metadata(4032, 3024, 3, None, None, None)
    
    assert "thumbnailId" not in result["system"]


def test_no_null_values():
    """Test 11: No null values"""
    exif_data = {
        "orientation": 1,
        "iso": 100,
    }
    
    gps_data = {
        "latitude": 32.0853,
        "longitude": 34.7818,
    }
    
    result = build_metadata(4032, 3024, 3, "abc123", exif_data, gps_data)
    
    def check_no_none(d):
        for v in d.values():
            if isinstance(v, dict):
                check_no_none(v)
            else:
                assert v is not None
    
    check_no_none(result)
