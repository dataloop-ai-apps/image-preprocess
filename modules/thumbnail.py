import logging
from io import BytesIO

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


def auto_rotate(img: Image.Image) -> Image.Image:
    """Apply EXIF orientation and return a new correctly-oriented image.
    If no orientation tag or error, returns the image unchanged (copy).
    """
    try:
        rotated = ImageOps.exif_transpose(img)
        if rotated is not None:
            return rotated
    except Exception as e:
        logger.warning(f"Failed to auto-rotate image: {e}")
    
    # Return a copy to avoid mutating input
    return img.copy()


def generate_thumbnail(img: Image.Image, max_edge: int = 512) -> BytesIO:
    """Generate a PNG thumbnail fitting within max_edge × max_edge.
    
    Input image should already be auto-rotated.
    Does NOT upscale — if image is smaller than max_edge, keeps original size.
    Converts to RGB if necessary (handles RGBA, P, L, LA, CMYK).
    Returns a BytesIO buffer containing PNG data, seeked to 0.
    """
    # Handle animated images - only process first frame
    if getattr(img, "is_animated", False):
        img.seek(0)
        img = img.copy()
    
    # Work on a copy to avoid mutating input
    thumb = img.copy()
    
    # Resize using thumbnail (never upscales, preserves aspect ratio)
    thumb.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    
    # Mode conversion before save
    if thumb.mode == "RGBA":
        # Composite over white background
        background = Image.new("RGB", thumb.size, (255, 255, 255))
        background.paste(thumb, mask=thumb.split()[3])
        thumb = background
    elif thumb.mode == "P":
        # Convert to RGBA first (may have transparency), then composite over white
        thumb = thumb.convert("RGBA")
        background = Image.new("RGB", thumb.size, (255, 255, 255))
        background.paste(thumb, mask=thumb.split()[3])
        thumb = background
    elif thumb.mode == "LA":
        # Composite over white background
        background = Image.new("RGB", thumb.size, (255, 255, 255))
        background.paste(thumb, mask=thumb.split()[1])
        thumb = background
    elif thumb.mode == "CMYK":
        # Direct convert to RGB
        thumb = thumb.convert("RGB")
    elif thumb.mode == "L":
        # Keep as L (valid in PNG)
        pass
    elif thumb.mode != "RGB":
        # Convert any other mode to RGB
        thumb = thumb.convert("RGB")
    
    # Save to BytesIO as PNG
    buf = BytesIO()
    thumb.save(buf, format="PNG")
    buf.seek(0)
    
    return buf
