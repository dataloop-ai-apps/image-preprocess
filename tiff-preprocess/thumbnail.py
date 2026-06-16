import logging
from io import BytesIO

import dtlpy as dl
from PIL import Image

from common.etl_errors import record_etl_error

logger = logging.getLogger("tiff-preprocess")


def generate_thumbnail(item: dl.Item, png_image: Image.Image, default_thumb_size: int) -> tuple[bool, str | None]:
    """Generate and upload a thumbnail from the in-memory converted PNG.

    Uses the PNG image and uploads the resized image directly from a BytesIO buffer.
    Mutates ``item.metadata`` in place when successful.
    """
    try:
        buf = make_thumbnail_buffer(png_image, default_thumb_size)
        thumbnail_item = item.dataset.items.upload(
            local_path=buf,
            remote_path='/.dataloop/thumbnails',
            remote_name='{}.png'.format(item.id),
            overwrite=True,
            item_metadata={'system': {'originItemId': item.id}},
        )
        item.metadata.setdefault('system', {})['thumbnailId'] = thumbnail_item.id
        logger.info('Thumbnail uploaded: item=%s thumb_id=%s', item.id, thumbnail_item.id)

    except Exception:
        logger.exception('Thumbnail generation failed for item=%s', item.id)
        record_etl_error(item, 'thumbnail', 'Thumbnail generation failed')


def make_thumbnail_buffer(pil_image: Image.Image, default_thumb_size: int) -> BytesIO:
    """Resize ``pil_image`` in place and return a PNG-encoded BytesIO buffer."""
    thumb = pil_image
    if thumb.mode != 'RGBA':
        thumb = thumb.convert('RGBA')
    thumb.thumbnail(size=(default_thumb_size, default_thumb_size))
    buf = BytesIO()
    thumb.save(buf, format='PNG')
    buf.seek(0)
    return buf
