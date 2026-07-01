import logging
import os
import sys
from io import BytesIO
from typing import Dict, Any

# Ensure repo root is importable so we can pull in the shared ``common`` package.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import dtlpy as dl
from PIL import Image, ImageOps
from PIL.ExifTags import Base, GPS, IFD

from common.etl_errors import record_etl_error, active_logger, report_progress

logger = logging.getLogger("image-preprocess")

# Defaults; override per-invocation via the trigger input.
MAX_FILE_SIZE_MB = 100
DEFAULT_THUMB_SIZE = 128


class ServiceRunner(dl.BaseServiceRunner):
    def __init__(self, **kwargs):
        pass

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def on_create(
        self,
        item: dl.Item,
        extract_metadata: bool = True,
        extract_thumbnail: bool = True,
        thumbnail_size: int = DEFAULT_THUMB_SIZE,
        max_file_size_mb: int = MAX_FILE_SIZE_MB,
        extract_exif: bool = True,
        extract_gps: bool = True,
        context=None,
        progress: "dl.Progress" = None,
    ):
        """Process an image item: extract metadata and generate thumbnail.

        If both extract flags are False, processing is skipped.

        ``context`` and ``progress`` are injected by the Dataloop runtime; they
        are optional so the method can also be driven directly (e.g. in tests).
        """
        log = active_logger(progress, context, default=logger)

        extract_metadata = bool(extract_metadata)
        extract_thumbnail = bool(extract_thumbnail)
        exif_enabled = bool(extract_exif)
        gps_enabled = bool(extract_gps)
        max_file_size_mb = int(max_file_size_mb)
        default_thumb_size = int(thumbnail_size)
        log.info(
            f"Config: extract_metadata={extract_metadata} extract_thumbnail={extract_thumbnail} "
            f"exif_enabled={exif_enabled} gps_enabled={gps_enabled}"
        )

        if not extract_metadata and not extract_thumbnail:
            log.info("Both extract_metadata and extract_thumbnail are False; skipping")
            return item

        report_progress(progress, message="Validating image", percent=5)

        try:
            # Clear stale ETL from previous runs
            item.metadata.setdefault("system", {}).pop("etl", None)

            # Reject non-image items
            mimetype = item.metadata.get("system", {}).get("mimetype", "")
            if not mimetype.startswith("image/"):
                msg = f"Unsupported mimetype: {mimetype}"
                log.error(msg)
                record_etl_error(item, stage="validation", error=msg, failed=True)
                raise ValueError(msg)

            # Download item and open image (single hard-failure path)
            report_progress(progress, message="Downloading image", percent=20)
            try:
                buffer = item.download(save_locally=False)
                if not isinstance(buffer, BytesIO):
                    buffer = BytesIO(buffer)
                buffer.seek(0)
                img = Image.open(buffer)
                img.load()
            except Exception as e:
                log.exception(f"Failed to download/open image from item {item.id}")
                record_etl_error(
                    item,
                    stage="download_open",
                    error=f"Failed to download/open image from item: {e}",
                    failed=True,
                )
                raise

            with buffer, img:
                if extract_metadata:
                    report_progress(progress, message="Extracting metadata", percent=45)
                    item.metadata["system"]["size"] = buffer.getbuffer().nbytes
                    self.set_image_dimensions(item, img)
                    try:
                        self.extract_exif(img, item,
                                          exif=exif_enabled, gps=gps_enabled)
                    except Exception as e:
                        log.exception(f"Failed to extract EXIF for item {item.id}")
                        record_etl_error(item, stage="exif", error=f"Exif extraction failed: {e}")

                # WARNING: thumbnail generation mutates img (resize in-place).
                # This MUST remain the last step that uses img.
                if extract_thumbnail:
                    report_progress(progress, message="Generating thumbnail", percent=70)
                    try:
                        self.create_and_upload_thumbnail(img, item, default_thumb_size)
                    except Exception as e:
                        log.exception(f"Failed to generate thumbnail for item {item.id}")
                        record_etl_error(item, stage="thumbnail", error=f"Thumbnail generation failed: {e}")
        finally:
            item = item.update(system_metadata=True)

        report_progress(progress, message="Done", percent=100)
        return item

    # ------------------------------------------------------------------
    # Metadata extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _ratio(val):
        if hasattr(val, "denominator"):
            return float(val.numerator) / float(val.denominator) if val.denominator != 0 else float(val.numerator)
        return float(val)

    @staticmethod
    def _clean_str(val):
        return str(val).strip().strip("\x00")

    @staticmethod
    def _iso(val):
        if isinstance(val, (tuple, list)):
            val = val[0]
        return int(val)

    @staticmethod
    def _exposure(val):
        if hasattr(val, "denominator") and val.denominator > 1:
            return f"{val.numerator}/{val.denominator}"
        return str(ServiceRunner._ratio(val))

    @staticmethod
    def set_image_dimensions(item, img: Image.Image):
        """Write image width, height, and channel count to item.metadata.system."""
        width, height = img.size
        channels = len(img.getbands())
        item.metadata["system"]["width"] = width
        item.metadata["system"]["height"] = height
        item.metadata["system"]["channels"] = channels

    @staticmethod
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

    @staticmethod
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

    def extract_exif(self, img: Image.Image, item, exif=True, gps=True):
        """Extract EXIF metadata from image and write to item.metadata.system.exif.

        Set *exif* or *gps* to ``False`` to skip the corresponding
        extraction entirely.
        Sets camelCase keys on item.metadata["system"]["exif"].
        Does nothing if no EXIF data exists.
        Caller is expected to wrap this in a try/except for non-fatal handling.
        """
        raw_exif = img.getexif()
        if not raw_exif:
            return

        if exif:
            exif_ifd = raw_exif.get_ifd(IFD.Exif)

            # (result_key, source, exif_tag, transform)
            fields = [
                ("orientation",       raw_exif, Base.Orientation,         int),
                ("camera_make",       raw_exif, Base.Make,                self._clean_str),
                ("camera_model",      raw_exif, Base.Model,               self._clean_str),
                ("date_time",         exif_ifd, Base.DateTimeOriginal,    self._clean_str),
                ("iso",               exif_ifd, Base.ISOSpeedRatings,     self._iso),
                ("aperture",          exif_ifd, Base.FNumber,             lambda v: round(self._ratio(v), 2)),
                ("exposure_time",     exif_ifd, Base.ExposureTime,        self._exposure),
                ("focal_length",      exif_ifd, Base.FocalLength,         lambda v: round(self._ratio(v), 3)),
                ("focal_length_35mm", exif_ifd, Base.FocalLengthIn35mmFilm, int),
                ("lens_model",        exif_ifd, Base.LensModel,           self._clean_str),
                ("flash",             exif_ifd, Base.Flash,               lambda v: bool(int(v) & 1)),
                ("white_balance",     exif_ifd, Base.WhiteBalance,        int),
            ]

            # DateTimeOriginal may live in main IFD on some files
            result = {}
            if raw_exif.get(Base.DateTimeOriginal) is not None and exif_ifd.get(Base.DateTimeOriginal) is None:
                exif_ifd[Base.DateTimeOriginal] = raw_exif.get(Base.DateTimeOriginal)

            for key, source, tag, transform in fields:
                raw = source.get(tag)
                if raw is None:
                    continue
                try:
                    result[key] = transform(raw)
                except Exception as e:
                    logger.warning(f"Failed to extract {key}: {e}")
            
            if result:
                item.metadata.setdefault("system", {})["exif"] = self.map_exif_keys(result)

        if gps:
            self.extract_gps(raw_exif, item)

    def _dms_to_decimal(self, dms, ref, negative_ref):
        """Convert a (deg, min, sec) tuple to signed decimal degrees."""
        deg, minutes, sec = (self._ratio(v) for v in dms[:3])
        decimal = deg + minutes / 60 + sec / 3600
        return -decimal if ref == negative_ref else decimal

    def extract_gps(self, exif, item):
        """Extract GPS coordinates from a PIL Exif object and write to item metadata.

        Sets item.metadata["system"]["location"] and item.metadata["user"]["location"].
        Does nothing if GPS data is absent or incomplete (both lat+lon required).
        Caller is expected to wrap this in a try/except for non-fatal handling.
        """
        gps_ifd = exif.get_ifd(IFD.GPSInfo)
        if not gps_ifd:
            return

        lat_ref, lat = gps_ifd.get(GPS.GPSLatitudeRef), gps_ifd.get(GPS.GPSLatitude)
        lon_ref, lon = gps_ifd.get(GPS.GPSLongitudeRef), gps_ifd.get(GPS.GPSLongitude)
        if lat is None or lat_ref is None or lon is None or lon_ref is None:
            return

        result = {
            "latitude": self._dms_to_decimal(lat, lat_ref, "S"),
            "longitude": self._dms_to_decimal(lon, lon_ref, "W"),
        }

        altitude = gps_ifd.get(GPS.GPSAltitude)
        if altitude is not None:
            alt_value = self._ratio(altitude)
            alt_ref = gps_ifd.get(GPS.GPSAltitudeRef)
            if alt_ref is not None:
                alt_ref_int = int.from_bytes(alt_ref, "big") if isinstance(alt_ref, bytes) else int(alt_ref)
                if alt_ref_int == 1:
                    alt_value = -alt_value
            result["altitude"] = alt_value

        location = self.build_location(result)
        item.metadata.setdefault("system", {})["location"] = location
        item.metadata.setdefault("user", {})["location"] = location

    # ------------------------------------------------------------------
    # Thumbnail generation
    # ------------------------------------------------------------------

    @staticmethod
    def auto_rotate(img: Image.Image, item) -> Image.Image:
        """Apply EXIF orientation and return a new correctly-oriented image.
        If no orientation tag, returns the image unchanged.
        Caller is expected to wrap this in a try/except for non-fatal handling.
        """
        rotated = ImageOps.exif_transpose(img)
        return rotated or img # if rotated is None, return the original image

    @staticmethod
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

    def create_and_upload_thumbnail(self, img: Image.Image, item, max_edge: int = 128):
        """Auto-rotate, generate thumbnail, upload to dataset, and set thumbnailId on item.

        Combines rotation correction, thumbnail generation, and upload into a single call.
        Sets item.metadata["system"]["thumbnailId"] but does NOT call item.update().
        Non-fatal errors are recorded via ``record_etl_error``.
        """
        rotated = self.auto_rotate(img, item)
        thumb_buf = self.generate_thumbnail(rotated, max_edge)
        thumbnail_item = item.dataset.items.upload(
            local_path=thumb_buf,
            remote_path="/.dataloop/thumbnails",
            remote_name=f"{item.id}.png",
            overwrite=True,
            item_metadata={"system": {"originItemId": item.id}}
        )
        item.metadata.setdefault("system", {})["thumbnailId"] = thumbnail_item.id

    # ------------------------------------------------------------------
    # Delete handler
    # ------------------------------------------------------------------

    @staticmethod
    def on_delete(item: dl.Item) -> None:
        """Clean up the generated thumbnail when the source image is deleted."""
        thumbnail_id = item.metadata.get("system", {}).get("thumbnailId")
        if thumbnail_id is None:
            logger.info("item=%s no thumbnailId in metadata, nothing to delete", item.id)
            return

        logger.info("item=%s deleting thumbnail id=%s", item.id, thumbnail_id)
        try:
            dl.items.get(item_id=thumbnail_id).delete()
            logger.info("item=%s thumbnail deleted", item.id)
        except dl.exceptions.NotFound:
            logger.info("item=%s thumbnail already deleted", item.id)
