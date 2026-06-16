import datetime
import logging

import dtlpy as dl
from PIL import Image

from common.etl_errors import record_etl_error

logger = logging.getLogger("tiff-preprocess")

INT32_MAX = 2147483647


# EXIF tag IDs (centralised so we don't sprinkle magic numbers in the code)
EXIF_TAG = {
    'BitsPerSample': 258,        # 0x0102
    'GPSInfoIFD': 34853,       # 0x8825
    'DateTimeOriginal': 36867,   # 0x9003
    'Model': 272,                # 0x0110
    'ExposureTime': 33434,       # 0x829A
    'FNumber': 33437,            # 0x829D
    'ISO': 34855,                # 0x8827 (ISOSpeedRatings)
    'WhiteBalance': 41987,       # 0xA403
    'Orientation': 274,          # 0x0112
}


def clamp_int32(value):
    """Clamp a numeric value to INT32_MAX to prevent metadata overflow."""
    if value is None:
        return None
    return min(int(value), INT32_MAX)


def read_exif_tags(item: dl.Item, pil_image: 'Image.Image'):
    """Read raw EXIF tags from a PIL image, returning None on failure."""
    try:
        return pil_image.getexif()
    except Exception as e:
        logger.warning('EXIF read failed: %s', e)
        record_etl_error(item, 'exif_read', str(e))
        return None


def extract_exif(item: dl.Item, exifdata) -> dict:
    """Extract EXIF metadata and GPS coordinates matching Rubiks field names."""
    result = {'exif': {}, 'location': {}}
    if not exifdata:
        return result
    try:
        tag_map = {
            'DateTimeOriginal': EXIF_TAG['DateTimeOriginal'],
            'Model':             EXIF_TAG['Model'],
            'ExposureTime':      EXIF_TAG['ExposureTime'],
            'FNumber':           EXIF_TAG['FNumber'],
            'ISO':               EXIF_TAG['ISO'],
            'WhiteBalance':      EXIF_TAG['WhiteBalance'],
            'Orientation':       EXIF_TAG['Orientation'],
        }

        for name, tag_id in tag_map.items():
            value = exifdata.get(tag_id)
            if value is not None:
                if name == 'DateTimeOriginal' and isinstance(value, str):
                    try:
                        dt = datetime.datetime.strptime(value, '%Y:%m:%d %H:%M:%S')
                        value = dt.isoformat() + 'Z'
                    except (ValueError, TypeError):
                        pass
                result['exif'][name] = value

        gps_ifd = exifdata.get_ifd(EXIF_TAG['GPSInfoIFD'])
        if gps_ifd:
            lat = parse_gps_coord(item, gps_ifd, 1, 2)
            lon = parse_gps_coord(item, gps_ifd, 3, 4)
            alt = gps_ifd.get(6)
            if lat is not None:
                result['location']['latitude'] = lat
            if lon is not None:
                result['location']['longitude'] = lon
            if alt is not None:
                result['location']['altitude'] = float(alt)
    except Exception as e:
        logger.warning('EXIF extraction failed', exc_info=True)
        record_etl_error(item, 'exif', str(e))

    return result


def parse_gps_coord(item: dl.Item, gps_ifd: dict, ref_tag: int,
                     coord_tag: int) -> float | None:
    """Convert GPS DMS (degrees/minutes/seconds) + N/S/E/W reference to decimal degrees."""
    try:
        ref = gps_ifd.get(ref_tag)
        coord = gps_ifd.get(coord_tag)
        if ref and coord and len(coord) == 3:
            degrees = float(coord[0])
            minutes = float(coord[1])
            seconds = float(coord[2])
            value = degrees + minutes / 60.0 + seconds / 3600.0
            if ref in ('S', 'W'):
                value = -value
            return value
    except (TypeError, ValueError, IndexError) as e:
        record_etl_error(item, 'gps_coord', str(e))
    return None


def validate_dimensions(item: dl.Item, width, height, channels) -> dict:
    """Validate extracted dimensions, clamp to INT32_MAX, and return dims dict."""
    if width is None or width <= 0:
        record_etl_error(item, 'dimensions', 'Invalid width: {}'.format(width))
    if height is None or height <= 0:
        record_etl_error(item, 'dimensions', 'Invalid height: {}'.format(height))
    if channels is None or channels <= 0:
        record_etl_error(item, 'dimensions', 'Invalid channels: {}'.format(channels))

    dims = {
        'width': clamp_int32(width) if width and width > 0 else None,
        'height': clamp_int32(height) if height and height > 0 else None,
        'channels': clamp_int32(channels) if channels and channels > 0 else None,
    }
    return dims
