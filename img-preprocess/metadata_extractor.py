import logging
from typing import Dict, Any

from PIL import Image
from PIL.ExifTags import Base, GPS, IFD

logger = logging.getLogger("image-preprocess")


def _ratio(val):
    if hasattr(val, "denominator"):
        return float(val.numerator) / float(val.denominator) if val.denominator != 0 else float(val.numerator)
    return float(val)


def _clean_str(val):
    return str(val).strip().strip("\x00")


def _iso(val):
    if isinstance(val, (tuple, list)):
        val = val[0]
    return int(val)


def _exposure(val):
    if hasattr(val, "denominator") and val.denominator > 1:
        return f"{val.numerator}/{val.denominator}"
    return str(_ratio(val))


def set_image_dimensions(item, img: Image.Image):
    """Write image width, height, and channel count to item.metadata.system."""
    width, height = img.size
    channels = len(img.getbands())
    item.metadata["system"]["width"] = width
    item.metadata["system"]["height"] = height
    item.metadata["system"]["channels"] = channels


def map_exif_keys(exif_data: Dict[str, Any]) -> Dict[str, Any]:
    """Map snake_case EXIF keys to camelCase for item.metadata.system.exif."""
    key_mapping = {
        "orientation": "orientation",
        "camera_make": "cameraMake",
        "camera_model": "cameraModel",
        "date_time": "dateTime",
        "iso": "iso",
        "aperture": "aperture",
        "exposure_time": "exposureTime",
        "focal_length": "focalLength",
        "focal_length_35mm": "focalLength35mm",
        "lens_model": "lensModel",
        "flash": "flash",
        "white_balance": "whiteBalance",
    }
    
    mapped = {}
    for snake_key, value in exif_data.items():
        if snake_key in key_mapping:
            mapped[key_mapping[snake_key]] = value
    
    return mapped


def build_location(gps_data: Dict[str, float]) -> Dict[str, float]:
    """Build location dict from GPS coordinates for item.metadata."""
    location = {
        "latitude": gps_data["latitude"],
        "longitude": gps_data["longitude"],
    }
    
    # Altitude is optional
    if "altitude" in gps_data:
        location["altitude"] = gps_data["altitude"]
    
    return location


def extract_exif(img: Image.Image, item, errors: list):
    """Extract EXIF metadata from image and write to item.metadata.system.exif.
    
    Sets camelCase keys on item.metadata["system"]["exif"].
    Does nothing if no EXIF data exists.
    Appends non-fatal errors to the provided ``errors`` list.
    """
    try:
        exif = img.getexif()
        if not exif:
            return
    except Exception as e:
        logger.warning(f"Failed to get EXIF data: {e}")
        errors.append(f"Exif extraction failed: {e}")
        return
    
    try:
        exif_ifd = exif.get_ifd(IFD.Exif)
    except Exception as e:
        logger.warning(f"Failed to get ExifIFD: {e}")
        exif_ifd = {}

    # (result_key, source, exif_tag, transform)
    fields = [
        ("orientation",       exif,     Base.Orientation,         int),
        ("camera_make",       exif,     Base.Make,                _clean_str),
        ("camera_model",      exif,     Base.Model,               _clean_str),
        ("date_time",         exif_ifd, Base.DateTimeOriginal,    _clean_str),
        ("iso",               exif_ifd, Base.ISOSpeedRatings,     _iso),
        ("aperture",          exif_ifd, Base.FNumber,             lambda v: round(_ratio(v), 2)),
        ("exposure_time",     exif_ifd, Base.ExposureTime,        _exposure),
        ("focal_length",      exif_ifd, Base.FocalLength,         lambda v: round(_ratio(v), 3)),
        ("focal_length_35mm", exif_ifd, Base.FocalLengthIn35mmFilm, int),
        ("lens_model",        exif_ifd, Base.LensModel,           _clean_str),
        ("flash",             exif_ifd, Base.Flash,               lambda v: bool(int(v) & 1)),
        ("white_balance",     exif_ifd, Base.WhiteBalance,        int),
    ]

    # DateTimeOriginal may live in main IFD on some files
    result = {}
    if exif.get(Base.DateTimeOriginal) is not None and exif_ifd.get(Base.DateTimeOriginal) is None:
        exif_ifd[Base.DateTimeOriginal] = exif.get(Base.DateTimeOriginal)

    for key, source, tag, transform in fields:
        raw = source.get(tag)
        if raw is None:
            continue
        try:
            result[key] = transform(raw)
        except Exception as e:
            logger.warning(f"Failed to extract {key}: {e}")
    
    if result:
        item.metadata.setdefault("system", {})["exif"] = map_exif_keys(result)

    extract_gps(exif, item, errors)


def _dms_to_decimal(dms, ref, negative_ref):
    """Convert a (deg, min, sec) tuple to signed decimal degrees."""
    deg, minutes, sec = (_ratio(v) for v in dms[:3])
    decimal = deg + minutes / 60 + sec / 3600
    return -decimal if ref == negative_ref else decimal


def extract_gps(exif, item, errors: list):
    """Extract GPS coordinates from a PIL Exif object and write to item metadata.

    Sets item.metadata["system"]["location"] and item.metadata["user"]["location"].
    Does nothing if GPS data is absent or incomplete (both lat+lon required).
    Appends non-fatal errors to the provided ``errors`` list.
    """
    try:
        gps_ifd = exif.get_ifd(IFD.GPSInfo)
        if not gps_ifd:
            return

        lat_ref, lat = gps_ifd.get(GPS.GPSLatitudeRef), gps_ifd.get(GPS.GPSLatitude)
        lon_ref, lon = gps_ifd.get(GPS.GPSLongitudeRef), gps_ifd.get(GPS.GPSLongitude)
        if lat is None or lat_ref is None or lon is None or lon_ref is None:
            return

        result = {
            "latitude": _dms_to_decimal(lat, lat_ref, "S"),
            "longitude": _dms_to_decimal(lon, lon_ref, "W"),
        }

        altitude = gps_ifd.get(GPS.GPSAltitude)
        if altitude is not None:
            alt_value = _ratio(altitude)
            alt_ref = gps_ifd.get(GPS.GPSAltitudeRef)
            if alt_ref is not None:
                alt_ref_int = int.from_bytes(alt_ref, "big") if isinstance(alt_ref, bytes) else int(alt_ref)
                if alt_ref_int == 1:
                    alt_value = -alt_value
            result["altitude"] = alt_value
    except Exception as e:
        errors.append(f"GPS extraction failed: {e}")
        logger.warning(f"Failed to extract GPS: {e}")
        return

    location = build_location(result)
    item.metadata.setdefault("system", {})["location"] = location
    item.metadata.setdefault("user", {})["location"] = location
