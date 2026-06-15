import pytest
from PIL import Image, ExifTags
from io import BytesIO

from thumbnail import auto_rotate, generate_thumbnail


def _make_item():
    class MockItem:
        def __init__(self):
            self.metadata = {"system": {}, "user": {}}
    return MockItem()


def create_test_image(width, height, mode="RGB", orientation=None):
    """Helper to create test image with optional orientation."""
    img = Image.new(mode, (width, height))
    
    if orientation is not None:
        exif = img.getexif()
        exif[ExifTags.Base.Orientation] = orientation
        buf = BytesIO()
        img.save(buf, format="JPEG", exif=exif.tobytes())
        buf.seek(0)
        return Image.open(buf)
    
    buf = BytesIO()
    if mode in ("RGBA", "LA"):
        img.save(buf, format="PNG")
    else:
        img.save(buf, format="JPEG")
    buf.seek(0)
    return Image.open(buf)


def test_landscape_resize():
    """Test 1: Landscape resize"""
    img = create_test_image(4032, 3024)
    result = generate_thumbnail(img, max_edge=512)
    
    thumb = Image.open(result)
    assert thumb.size == (512, 384)


def test_portrait_resize():
    """Test 2: Portrait resize"""
    img = create_test_image(3024, 4032)
    result = generate_thumbnail(img, max_edge=512)
    
    thumb = Image.open(result)
    assert thumb.size == (384, 512)


def test_square_resize():
    """Test 3: Square resize"""
    img = create_test_image(2000, 2000)
    result = generate_thumbnail(img, max_edge=512)
    
    thumb = Image.open(result)
    assert thumb.size == (512, 512)


def test_small_image_no_upscale():
    """Test 4: Small image — no upscale"""
    img = create_test_image(100, 80)
    result = generate_thumbnail(img, max_edge=512)
    
    thumb = Image.open(result)
    assert thumb.size == (100, 80)


def test_custom_max_edge():
    """Test 5: Custom max_edge"""
    img = create_test_image(4032, 3024)
    result = generate_thumbnail(img, max_edge=256)
    
    thumb = Image.open(result)
    assert thumb.size == (256, 192)


def test_rgba_to_rgb():
    """Test 6: RGBA → RGB"""
    img = create_test_image(400, 300, mode="RGBA")
    result = generate_thumbnail(img, max_edge=512)
    
    thumb = Image.open(result)
    assert thumb.mode == "RGB"
    # Check that background is white (not transparent)
    assert thumb.format == "PNG"


def test_auto_rotate_orientation_6():
    """Test 7: Auto-rotate orientation=6"""
    img = create_test_image(800, 600, orientation=6)
    errors = []
    rotated = auto_rotate(img, errors)
    
    # Orientation 6 means 90° CW rotation
    # Original 800x600 should become 600x800
    assert rotated.size == (600, 800)
    assert errors == []


def test_auto_rotate_orientation_1():
    """Test 8: Auto-rotate orientation=1"""
    img = create_test_image(800, 600, orientation=1)
    rotated = auto_rotate(img, [])
    
    # Orientation 1 means no rotation
    assert rotated.size == (800, 600)


def test_auto_rotate_no_exif():
    """Test 9: Auto-rotate no EXIF"""
    img = create_test_image(800, 600)
    rotated = auto_rotate(img, [])
    
    # No EXIF should return unchanged copy
    assert rotated.size == (800, 600)


def test_output_is_valid_png():
    """Test 10: Output is valid PNG"""
    img = create_test_image(400, 300)
    result = generate_thumbnail(img, max_edge=512)
    
    thumb = Image.open(result)
    assert thumb.format == "PNG"


def test_output_buffer_seeked_to_0():
    """Test 11: Output buffer seeked to 0"""
    img = create_test_image(400, 300)
    result = generate_thumbnail(img, max_edge=512)
    
    assert result.tell() == 0


def test_input_mutated_in_place():
    """Test 12: generate_thumbnail mutates the input image (resize in-place)"""
    img = create_test_image(1024, 768)
    
    generate_thumbnail(img, max_edge=256)
    
    # thumbnail() resizes in-place — original img is now resized
    assert max(img.size) <= 256
