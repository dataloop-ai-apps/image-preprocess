import logging
import os
from io import BytesIO

import dtlpy as dl
from PIL import Image

from metadata_extractor import extract_exif, extract_gps, set_image_dimensions
from thumbnail import create_and_upload_thumbnail

logger = logging.getLogger("image-preprocess")

ENABLE_IMAGE_PREPROCESS = os.getenv("ENABLE_IMAGE_PREPROCESS", "true").lower() == "true"
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
DEFAULT_THUMB_SIZE = int(os.getenv("DEFAULT_THUMB_SIZE", "128"))
DEFAULT_MODE = os.getenv("DEFAULT_MODE", "full")


class ServiceRunner(dl.BaseServiceRunner):
    def __init__(self, **kwargs):
        pass

    def on_create(self, item: dl.Item, context=None, progress=None):
        """Process an image item: extract metadata and generate thumbnail.
        
        Processing mode is controlled via context.trigger_input:
            mode – "full" | "metadata-only" | "thumbnail-only" (default: "full")
        """
        
        # Resolve config from trigger input, fallback to env defaults
        trigger_input = {}
        if context is not None and hasattr(context, 'trigger_input'):
            trigger_input = context.trigger_input or {}
        
        mode = trigger_input.get('mode', DEFAULT_MODE)
        max_file_size_mb = int(trigger_input.get('max_file_size_mb', MAX_FILE_SIZE_MB))
        default_thumb_size = int(trigger_input.get('default_thumb_size', DEFAULT_THUMB_SIZE))
        logger.info(f"Processing mode: {mode}")
        
        if not ENABLE_IMAGE_PREPROCESS:
            logger.info("Image preprocessing disabled via ENABLE_IMAGE_PREPROCESS")
            return item
        
        # Clear stale ETL from previous runs
        item.metadata.setdefault("system", {}).pop("etl", None)

        # Reject non-image items
        mimetype = item.metadata.get("system", {}).get("mimetype", "")
        if not mimetype.startswith("image/"):
            logger.info(f"Skipping non-image item: {mimetype}")
            item.metadata["system"]["etl"] = {"failed": True, "errors": [f"Unsupported mimetype: {mimetype}"]}
            item = item.update(system_metadata=True)
            return item
        
        # Reject files exceeding size limit
        file_size = item.metadata.get("system", {}).get("size", 0)
        if file_size > max_file_size_mb * 1024 * 1024:
            logger.error(f"File too large: {file_size} bytes > {max_file_size_mb}MB")
            item.metadata["system"]["etl"] = {
                "failed": True,
                "errors": [f"File too large: {file_size} bytes exceeds {max_file_size_mb}MB limit"],
            }
            item = item.update(system_metadata=True)
            return item
        
        # Download item binary content
        try:
            buffer = item.download(save_locally=False)
            if not isinstance(buffer, BytesIO):
                buffer = BytesIO(buffer)
        except Exception as e:
            logger.exception(f"Failed to download item {item.id}")
            item.metadata["system"]["etl"] = {
                "failed": True,
                "errors": [f"Download failed: {e}"],
            }
            item = item.update(system_metadata=True)
            return item
        
        # Open image and write dimensions to metadata
        try:
            buffer.seek(0)
            img = Image.open(buffer)
            img.load()
        except Exception as e:
            logger.exception(f"Failed to open/read image for item {item.id}")
            item.metadata["system"]["etl"] = {
                "failed": True,
                "errors": [f"Image metadata extraction failed: {e}"],
            }
            item = item.update(system_metadata=True)
            buffer.close()
            return item
        
        set_image_dimensions(item, img)

        # Extract EXIF and GPS, each writes directly to item.metadata
        if mode in ('full', 'metadata-only'):
            try:
                extract_exif(img, item)
                extract_gps(img, item)
            except Exception as e:
                logger.exception(f"Failed to extract EXIF for item {item.id}")
                item.metadata["system"].setdefault("etl", {}).setdefault("errors", []).append(f"Exif extraction failed: {e}")
        
        # WARNING: thumbnail generation mutates img (resize in-place).
        # This MUST remain the last step that uses img.
        if mode in ('full', 'thumbnail-only'):
            try:
                create_and_upload_thumbnail(img, item, default_thumb_size)
            except Exception as e:
                logger.exception(f"Failed to generate thumbnail for item {item.id}")
                item.metadata["system"].setdefault("etl", {}).setdefault("errors", []).append(f"Thumbnail generation failed: {e}")
        
        item = item.update(system_metadata=True)
        return item
