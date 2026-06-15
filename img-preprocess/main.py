import logging
import os
from io import BytesIO

import dtlpy as dl
from PIL import Image

from exif_extractor import extract_exif, extract_gps
from thumbnail import auto_rotate, generate_thumbnail
from metadata import build_metadata

logger = logging.getLogger(__name__)

# Configuration (§5.6)
ENABLE_IMAGE_PREPROCESS = os.getenv("ENABLE_IMAGE_PREPROCESS", "true").lower() == "true"
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
DEFAULT_THUMB_SIZE = int(os.getenv("DEFAULT_THUMB_SIZE", "128"))
DEFAULT_MODE = os.getenv("DEFAULT_MODE", "full")


class ServiceRunner(dl.BaseServiceRunner):
    def __init__(self, **kwargs):
        pass

    def on_create(self, item: dl.Item, context=None, progress=None):
        """Process an image item: extract metadata and generate thumbnail.
        
        The trigger's spec.input (via context.trigger_input) controls processing mode:
            mode – "full" | "metadata-only" | "thumbnail-only" (default: "full")
        """
        
        # Resolve processing config from trigger input, fallback to env vars
        trigger_input = {}
        if context is not None and hasattr(context, 'trigger_input'):
            trigger_input = context.trigger_input or {}
        
        mode = trigger_input.get('mode', DEFAULT_MODE)
        max_file_size_mb = int(trigger_input.get('max_file_size_mb', MAX_FILE_SIZE_MB))
        default_thumb_size = int(trigger_input.get('default_thumb_size', DEFAULT_THUMB_SIZE))
        logger.info(f"Processing mode: {mode}")
        
        # Step 1: ENABLE_IMAGE_PREPROCESS check
        if not ENABLE_IMAGE_PREPROCESS:
            logger.info("Image preprocessing disabled via ENABLE_IMAGE_PREPROCESS")
            return item
        
        # Clear stale ETL from previous runs
        item.metadata.setdefault("system", {}).pop("etl", None)

        # Step 2: MIME guard
        mimetype = item.metadata.get("system", {}).get("mimetype", "")
        if not mimetype.startswith("image/"):
            logger.info(f"Skipping non-image item: {mimetype}")
            item.metadata["system"]["etl"] = {"failed": True, "errors": [f"Unsupported mimetype: {mimetype}"]}
            item = item.update(system_metadata=True)
            return item
        
        # Step 3: File size guard
        file_size = item.metadata.get("system", {}).get("size", 0)
        if file_size > max_file_size_mb * 1024 * 1024:
            logger.warning(f"File too large: {file_size} bytes > {max_file_size_mb}MB")
            return item
        
        # Step 4: Download to BytesIO
        try:
            buffer = item.download(save_locally=False)
            if not isinstance(buffer, BytesIO):
                buffer = BytesIO(buffer)
        except Exception as e:
            logger.exception(f"Failed to download item {item.id}")
            raise
        
        # Step 5-6: Open with Pillow and extract dimensions
        try:
            buffer.seek(0)
            img = Image.open(buffer)
            img.load()
            width, height = img.size
            channels = len(img.getbands())
        except Exception as e:
            logger.exception(f"Failed to open/read image for item {item.id}")
            item.metadata["system"]["etl"] = {
                "failed": True,
                "errors": [f"Image metadata extraction failed: {e}"],
            }
            item = item.update(system_metadata=True)
            buffer.close()
            return item
        
        # ETL info accumulator
        etl_info = {}

        # Step 7: Metadata extraction (non-fatal block)
        exif_data = None
        gps_data = None
        
        if mode in ('full', 'metadata-only'):
            try:
                exif_data = extract_exif(img)
                gps_data = extract_gps(img)
            except Exception as e:
                logger.exception(f"Failed to extract EXIF for item {item.id}")
                etl_info.setdefault("errors", []).append(f"Exif extraction failed: {e}")
                exif_data = None
                gps_data = None
        
        # Step 8-9: Thumbnail (non-fatal block)
        thumbnail_id = None
        
        if mode in ('full', 'thumbnail-only'):
            try:
                rotated = auto_rotate(img)
                thumb_buf = generate_thumbnail(rotated, default_thumb_size)
                dataset = dl.datasets.get(dataset_id=item.datasetId, fetch=False)
                thumbnail_item = dataset.items.upload(
                    local_path=thumb_buf,
                    remote_path="/.dataloop/thumbnails",
                    remote_name=f"{item.id}.png",
                    overwrite=True,
                    item_metadata={"system": {"originItemId": item.id}}
                )
                thumbnail_id = thumbnail_item.id
            except Exception as e:
                logger.exception(f"Failed to generate thumbnail for item {item.id}")
                etl_info.setdefault("errors", []).append(f"Thumbnail generation failed: {e}")
        
        # Step 10: Build metadata
        meta = build_metadata(width, height, channels, thumbnail_id, exif_data, gps_data)
        
        # Step 11-12: Write metadata
        item.metadata.setdefault("system", {}).update(meta["system"])
        if "user" in meta:
            item.metadata.setdefault("user", {}).update(meta["user"])
        
        # Write ETL info only if there were issues
        if etl_info:
            item.metadata["system"]["etl"] = etl_info
        
        # Step 13: Update item
        item = item.update(system_metadata=True)
        return item
