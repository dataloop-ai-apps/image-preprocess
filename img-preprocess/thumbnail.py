import logging
from io import BytesIO

from PIL import Image, ImageOps

from etl_errors import record_etl_error

logger = logging.getLogger("image-preprocess")


def auto_rotate(img: Image.Image, item) -> Image.Image:
    """Apply EXIF orientation and return a new correctly-oriented image.
    If no orientation tag or error, returns the image unchanged (copy).
    Non-fatal errors are recorded via ``record_etl_error``.
    """
    try:
        rotated = ImageOps.exif_transpose(img)
        if rotated is not None:
            return rotated
    except Exception as e:
        logger.warning(f"Failed to auto-rotate image: {e}")
        record_etl_error(item, stage="thumbnail", error=f"Auto-rotate failed: {e}")

    return img


def generate_thumbnail(img: Image.Image, max_edge: int = 512) -> BytesIO:
    """Generate a PNG thumbnail fitting within max_edge × max_edge.
    
    Input image should already be auto-rotated.
    Does NOT upscale — if image is smaller than max_edge, keeps original size.
    Converts to RGB if necessary (handles RGBA, P, L, LA, CMYK).
    Returns a BytesIO buffer containing PNG data, seeked to 0.
    
    WARNING: This function may mutate the input image (e.g. resize in-place).
    Callers must treat img as consumed after this call.
    """
    # Animated images (e.g. GIF): seek to frame 0 and copy to extract a
    # single static frame. Without copy, thumbnail() operates on the full
    # multi-frame object which can produce errors or unexpected results.
    if getattr(img, "is_animated", False):
        img.seek(0)
        img = img.copy()
    
    thumb = img
    
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


def create_and_upload_thumbnail(img: Image.Image, item, max_edge: int = 128):
    """Auto-rotate, generate thumbnail, upload to dataset, and set thumbnailId on item.

    Combines rotation correction, thumbnail generation, and upload into a single call.
    Sets item.metadata["system"]["thumbnailId"] but does NOT call item.update().
    Non-fatal errors are recorded via ``record_etl_error``.
    """
    rotated = auto_rotate(img, item)
    thumb_buf = generate_thumbnail(rotated, max_edge)
    thumbnail_item = item.dataset.items.upload(
        local_path=thumb_buf,
        remote_path="/.dataloop/thumbnails",
        remote_name=f"{item.id}.png",
        overwrite=True,
        item_metadata={"system": {"originItemId": item.id}}
    )
    item.metadata.setdefault("system", {})["thumbnailId"] = thumbnail_item.id
