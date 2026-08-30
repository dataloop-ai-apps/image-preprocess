from PIL import Image

from main import ServiceRunner

build_location = ServiceRunner.build_location
set_image_dimensions = ServiceRunner.set_image_dimensions


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
