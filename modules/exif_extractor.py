import logging
from typing import Dict, Optional

from PIL import Image
from PIL.ExifTags import Base, GPS, IFD

logger = logging.getLogger(__name__)


def extract_exif(img: Image.Image) -> Optional[Dict[str, any]]:
    """Extract EXIF metadata from a Pillow Image.
    
    Returns a dict with snake_case keys for present fields,
    or None if no EXIF data exists at all.
    """
    try:
        exif = img.getexif()
        if not exif:
            return None
    except Exception as e:
        logger.warning(f"Failed to get EXIF data: {e}")
        return None
    
    result = {}
    
    # Main IFD tags
    try:
        orientation = exif.get(Base.Orientation)
        if orientation is not None:
            result["orientation"] = int(orientation)
    except Exception as e:
        logger.warning(f"Failed to extract orientation: {e}")
    
    try:
        make = exif.get(Base.Make)
        if make is not None:
            result["camera_make"] = str(make).strip().strip('\x00')
    except Exception as e:
        logger.warning(f"Failed to extract camera make: {e}")
    
    try:
        model = exif.get(Base.Model)
        if model is not None:
            result["camera_model"] = str(model).strip().strip('\x00')
    except Exception as e:
        logger.warning(f"Failed to extract camera model: {e}")
    
    # EXIF sub-IFD (IFD 0x8769)
    try:
        exif_ifd = exif.get_ifd(IFD.Exif)
    except Exception as e:
        logger.warning(f"Failed to get ExifIFD: {e}")
        exif_ifd = {}
    
    try:
        date_time = exif.get(Base.DateTimeOriginal) or exif_ifd.get(Base.DateTimeOriginal)
        if date_time is not None:
            result["date_time"] = str(date_time).strip().strip('\x00')
    except Exception as e:
        logger.warning(f"Failed to extract date time: {e}")
    
    try:
        iso = exif_ifd.get(Base.ISOSpeedRatings)
        if iso is not None:
            # ISO can be a tuple/list on some cameras
            if isinstance(iso, (tuple, list)):
                iso = iso[0]
            result["iso"] = int(iso)
    except Exception as e:
        logger.warning(f"Failed to extract ISO: {e}")
    
    try:
        f_number = exif_ifd.get(Base.FNumber)
        if f_number is not None:
            if hasattr(f_number, 'denominator'):
                if f_number.denominator != 0:
                    result["aperture"] = round(float(f_number.numerator) / float(f_number.denominator), 2)
                else:
                    result["aperture"] = round(float(f_number.numerator), 2)
            else:
                result["aperture"] = round(float(f_number), 2)
    except Exception as e:
        logger.warning(f"Failed to extract aperture: {e}")
    
    try:
        exposure_time = exif_ifd.get(Base.ExposureTime)
        if exposure_time is not None:
            if hasattr(exposure_time, 'denominator'):
                if exposure_time.denominator != 0:
                    if exposure_time.denominator > 1:
                        result["exposure_time"] = f"{exposure_time.numerator}/{exposure_time.denominator}"
                    else:
                        result["exposure_time"] = str(float(exposure_time.numerator / exposure_time.denominator))
                else:
                    result["exposure_time"] = str(float(exposure_time.numerator))
            else:
                result["exposure_time"] = str(float(exposure_time))
    except Exception as e:
        logger.warning(f"Failed to extract exposure time: {e}")
    
    try:
        focal_length = exif_ifd.get(Base.FocalLength)
        if focal_length is not None:
            if hasattr(focal_length, 'denominator') and focal_length.denominator != 0:
                result["focal_length"] = round(float(focal_length.numerator / focal_length.denominator), 3)
            else:
                result["focal_length"] = round(float(focal_length), 3)
    except Exception as e:
        logger.warning(f"Failed to extract focal length: {e}")
    
    try:
        focal_length_35mm = exif_ifd.get(Base.FocalLengthIn35mmFilm)
        if focal_length_35mm is not None:
            result["focal_length_35mm"] = int(focal_length_35mm)
    except Exception as e:
        logger.warning(f"Failed to extract focal length 35mm: {e}")
    
    try:
        lens_model = exif_ifd.get(Base.LensModel)
        if lens_model is not None:
            result["lens_model"] = str(lens_model).strip().strip('\x00')
    except Exception as e:
        logger.warning(f"Failed to extract lens model: {e}")
    
    try:
        flash = exif_ifd.get(Base.Flash)
        if flash is not None:
            # Bit 0 indicates if flash fired
            result["flash"] = bool(int(flash) & 1)
    except Exception as e:
        logger.warning(f"Failed to extract flash: {e}")
    
    try:
        white_balance = exif_ifd.get(Base.WhiteBalance)
        if white_balance is not None:
            result["white_balance"] = int(white_balance)
    except Exception as e:
        logger.warning(f"Failed to extract white balance: {e}")
    
    return result if result else None


def extract_gps(img: Image.Image) -> Optional[Dict[str, float]]:
    """Extract GPS coordinates from EXIF.
    
    Returns {"latitude": float, "longitude": float, "altitude": float}
    or None if GPS data is absent/incomplete (both lat+lon required).
    Latitude/longitude are signed decimal degrees (S/W = negative).
    Altitude is meters; negative if below sea level (GPSAltitudeRef=1).
    Altitude is optional within the returned dict.
    """
    try:
        exif = img.getexif()
        if not exif:
            return None
    except Exception as e:
        logger.warning(f"Failed to get EXIF data for GPS: {e}")
        return None
    
    try:
        gps_ifd = exif.get_ifd(IFD.GPSInfo)
        if not gps_ifd:
            return None
    except Exception as e:
        logger.warning(f"Failed to get GPS IFD: {e}")
        return None
    
    result = {}
    
    # Latitude
    try:
        lat_ref = gps_ifd.get(GPS.GPSLatitudeRef)
        lat = gps_ifd.get(GPS.GPSLatitude)
        
        if lat_ref is None or lat is None:
            return None
        
        # Convert DMS to decimal degrees
        def to_float(val):
            if hasattr(val, 'denominator'):
                return float(val.numerator / val.denominator) if val.denominator != 0 else float(val.numerator)
            return float(val)
        
        lat_deg = to_float(lat[0])
        lat_min = to_float(lat[1])
        lat_sec = to_float(lat[2])
        
        latitude = lat_deg + lat_min / 60 + lat_sec / 3600
        
        if lat_ref == "S":
            latitude = -latitude
        
        result["latitude"] = latitude
    except Exception as e:
        logger.warning(f"Failed to extract latitude: {e}")
        return None
    
    # Longitude
    try:
        lon_ref = gps_ifd.get(GPS.GPSLongitudeRef)
        lon = gps_ifd.get(GPS.GPSLongitude)
        
        if lon_ref is None or lon is None:
            return None
        
        # Convert DMS to decimal degrees
        lon_deg = to_float(lon[0])
        lon_min = to_float(lon[1])
        lon_sec = to_float(lon[2])
        
        longitude = lon_deg + lon_min / 60 + lon_sec / 3600
        
        if lon_ref == "W":
            longitude = -longitude
        
        result["longitude"] = longitude
    except Exception as e:
        logger.warning(f"Failed to extract longitude: {e}")
        return None
    
    # Altitude (optional)
    try:
        alt_ref = gps_ifd.get(GPS.GPSAltitudeRef)
        altitude = gps_ifd.get(GPS.GPSAltitude)
        
        if altitude is not None:
            if hasattr(altitude, 'denominator'):
                alt_value = float(altitude.numerator) / float(altitude.denominator) if altitude.denominator != 0 else float(altitude.numerator)
            else:
                alt_value = float(altitude)
            
            # GPSAltitudeRef: 0 = above sea level, 1 = below sea level
            # May be bytes or int
            if alt_ref is not None:
                if isinstance(alt_ref, bytes):
                    alt_ref_int = int.from_bytes(alt_ref, byteorder='big')
                else:
                    alt_ref_int = int(alt_ref)
                if alt_ref_int == 1:
                    alt_value = -alt_value
            
            result["altitude"] = alt_value
    except Exception as e:
        logger.warning(f"Failed to extract altitude: {e}")
        # Altitude is optional, so don't fail if extraction fails
    
    return result
