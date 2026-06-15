from PIL import Image

from metadata_extractor import map_exif_keys, build_location, set_image_dimensions


def test_full_exif_key_mapping():
    """All snake_case EXIF keys are mapped to camelCase"""
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
    
    result = map_exif_keys(exif_data)
    
    assert result["orientation"] == 1
    assert result["cameraMake"] == "Apple"
    assert result["cameraModel"] == "iPhone 15 Pro"
    assert result["dateTime"] == "2024:01:15 10:30:45"
    assert result["iso"] == 100
    assert result["aperture"] == 1.78
    assert result["exposureTime"] == "1/120"
    assert result["focalLength"] == 6.765
    assert result["focalLength35mm"] == 24
    assert result["lensModel"] == "iPhone 15 Pro back camera 6.765mm f/1.78"
    assert result["flash"] is False
    assert result["whiteBalance"] == 0
    
    # Ensure snake_case keys are NOT present
    assert "camera_make" not in result
    assert "camera_model" not in result
    assert "date_time" not in result
    assert "exposure_time" not in result
    assert "focal_length" not in result
    assert "focal_length_35mm" not in result
    assert "lens_model" not in result
    assert "white_balance" not in result


def test_partial_exif_key_mapping():
    """Only present keys are mapped"""
    exif_data = {
        "orientation": 1,
        "iso": 100,
    }
    
    result = map_exif_keys(exif_data)
    
    assert result["orientation"] == 1
    assert result["iso"] == 100
    assert "cameraMake" not in result


def test_empty_exif_returns_empty():
    """Empty dict returns empty dict"""
    result = map_exif_keys({})
    assert result == {}


def test_unknown_keys_ignored():
    """Keys not in the mapping are silently dropped"""
    exif_data = {
        "orientation": 1,
        "unknown_key": "value",
    }
    
    result = map_exif_keys(exif_data)
    assert result == {"orientation": 1}


def test_build_location_lat_lon():
    """Lat/lon are required in the output"""
    gps_data = {"latitude": 32.0853, "longitude": 34.7818}
    result = build_location(gps_data)
    
    assert result["latitude"] == 32.0853
    assert result["longitude"] == 34.7818
    assert "altitude" not in result


def test_build_location_with_altitude():
    """Altitude is included when present"""
    gps_data = {"latitude": 32.0853, "longitude": 34.7818, "altitude": 15.0}
    result = build_location(gps_data)
    
    assert result["altitude"] == 15.0


def test_build_location_no_null_values():
    """No None values in the returned dict"""
    gps_data = {"latitude": 32.0853, "longitude": 34.7818, "altitude": 15.0}
    result = build_location(gps_data)
    
    for v in result.values():
        assert v is not None


def test_set_image_dimensions_rgb():
    """Writes width, height, channels to item.metadata.system"""
    class MockItem:
        def __init__(self):
            self.metadata = {"system": {}}
    
    item = MockItem()
    img = Image.new("RGB", (800, 600))
    set_image_dimensions(item, img)
    
    assert item.metadata["system"]["width"] == 800
    assert item.metadata["system"]["height"] == 600
    assert item.metadata["system"]["channels"] == 3


def test_set_image_dimensions_rgba():
    """RGBA image reports 4 channels"""
    class MockItem:
        def __init__(self):
            self.metadata = {"system": {}}
    
    item = MockItem()
    img = Image.new("RGBA", (1024, 768))
    set_image_dimensions(item, img)
    
    assert item.metadata["system"]["channels"] == 4
