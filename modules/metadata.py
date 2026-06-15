from typing import Dict, Optional, Any


def build_metadata(
    width: int,
    height: int,
    channels: int,
    thumbnail_id: Optional[str],
    exif_data: Optional[Dict[str, Any]],
    gps_data: Optional[Dict[str, float]],
) -> Dict[str, Dict[str, Any]]:
    """Build a dict describing what to merge into item.metadata.
    
    Returns:
    {
        "system": { ... },   # always present
        "user": { ... },     # only if GPS data present (backward compat)
    }
    """
    result = {
        "system": {
            "width": width,
            "height": height,
            "channels": channels,
        }
    }
    
    # Add thumbnailId if provided
    if thumbnail_id is not None:
        result["system"]["thumbnailId"] = thumbnail_id
    
    # Add EXIF data — only present if EXIF data exists
    if exif_data:
        exif_mapped = _map_exif_keys(exif_data)
        if exif_mapped:
            result["system"]["exif"] = exif_mapped
    
    # Add GPS/location — only present if GPS data exists
    if gps_data:
        location = _build_location(gps_data)
        result["system"]["location"] = location
        result["user"] = {
            "location": location
        }
    
    return result


def _map_exif_keys(exif_data: Dict[str, Any]) -> Dict[str, Any]:
    """Map snake_case EXIF keys to camelCase."""
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


def _build_location(gps_data: Dict[str, float]) -> Dict[str, float]:
    """Build location dict from GPS data."""
    location = {
        "latitude": gps_data["latitude"],
        "longitude": gps_data["longitude"],
    }
    
    # Altitude is optional
    if "altitude" in gps_data:
        location["altitude"] = gps_data["altitude"]
    
    return location
