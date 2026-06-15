import traceback
import os
import sys
import datetime
import logging
import math
from io import BytesIO

# Ensure repo root is importable so we can pull in the shared ``common`` package.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import numpy as np
import rasterio
import dtlpy as dl
from PIL import Image

from common.etl_errors import record_etl_error

logger = logging.getLogger("tiff-preprocess")

INT32_MAX = 2147483647

# Thumbnail / processing configuration
DEFAULT_THUMB_SIZE = int(os.environ.get('DEFAULT_THUMB_SIZE', '128'))
# DEFAULT_MODE: 'full' | 'metadata-only' | 'thumbnail-only'
DEFAULT_MODE = os.environ.get('DEFAULT_MODE', 'full').lower()

# Max input TIFF file size (MB). Larger than typical images since TIFFs can be big.
MAX_FILE_SIZE_MB = int(os.environ.get('TIFF_MAX_FILE_SIZE_MB', '2000'))

# GDAL dtype mapping: numpy dtype string -> (gdal_type_code, gdal_type_name)
GDAL_DTYPE_MAP = {
    'uint8': (1, 'Byte'),
    'int8': (1, 'Byte'),
    'uint16': (2, 'UInt16'),
    'int16': (3, 'Int16'),
    'uint32': (4, 'UInt32'),
    'int32': (5, 'Int32'),
    'float32': (6, 'Float32'),
    'float64': (7, 'Float64'),
    'complex64': (10, 'CFloat32'),
    'complex128': (11, 'CFloat64'),
}

# Projects to skip (comma-separated UUIDs)
SKIP_PROJECTS = set(os.environ.get('TIFF_SKIP_PROJECTS', '').split(','))

# Dataset-level metadata flag name to check for skipping
SKIP_DATASET_FLAG = os.environ.get('TIFF_SKIP_DATASET_FLAG', 'skipTiffConversion')


class ServiceRunner(dl.BaseServiceRunner):

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

    def __init__(self, **kwargs):
        # Disable PIL's decompression bomb safety: TIFFs are legitimately huge.
        Image.MAX_IMAGE_PIXELS = None
        # Per-run state. Reset at the start of every run().
        # NOTE: this makes ServiceRunner non-reentrant — one item per worker at a time.
        self.tiff_filepath: str | None = None
        self.png_image: Image.Image | None = None
        self.pil_image: Image.Image | None = None
        self.is_multibit: bool = True
        self.exif_data: dict = {'exif': {}, 'location': {}}
        self.tiff_meta: dict = {}
        self.shape: tuple | None = None
        self.dims: dict | None = None
        self.mode: str = DEFAULT_MODE
        self.max_file_size_mb: int = MAX_FILE_SIZE_MB
        self.default_thumb_size: int = DEFAULT_THUMB_SIZE
        logger.info(
            'ServiceRunner initialized: thumb_size=%d, mode=%s, max_file_size_mb=%d',
            DEFAULT_THUMB_SIZE, DEFAULT_MODE, MAX_FILE_SIZE_MB,
        )

    @staticmethod
    def clamp_int32(value):
        """Clamp a numeric value to INT32_MAX to prevent metadata overflow."""
        if value is None:
            return None
        return min(int(value), INT32_MAX)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self, item: dl.Item, context=None, progress: dl.Progress | None = None) -> None:
        if self._should_skip(item):
            return

        # Resolve config from trigger input, fallback to env defaults
        trigger_input = {}
        if context is not None and hasattr(context, 'trigger_input'):
            trigger_input = context.trigger_input or {}

        self.mode = str(trigger_input.get('mode', DEFAULT_MODE)).lower()
        self.max_file_size_mb = int(trigger_input.get('max_file_size_mb', MAX_FILE_SIZE_MB))
        self.default_thumb_size = int(trigger_input.get('default_thumb_size', DEFAULT_THUMB_SIZE))
        logger.info('Processing config: mode=%s max_file_size_mb=%d default_thumb_size=%d',
                    self.mode, self.max_file_size_mb, self.default_thumb_size)

        do_metadata = self.mode in ('full', 'metadata-only')
        do_thumbnail = self.mode in ('full', 'thumbnail-only')

        # Ensure the etl error sink exists; all helpers route through _record_etl_error.
        item.metadata.setdefault('system', {}).setdefault('etl', {}).setdefault('errors', [])
        self.tiff_filepath = None
        self.png_image = None
        self.pil_image = None
        self.is_multibit = True
        self.exif_data = {'exif': {}, 'location': {}}
        self.tiff_meta = {}
        self.shape = None
        self.dims = None

        try:
            # File size guard (uses platform-reported size to avoid downloading huge files).
            file_size = item.metadata.get('system', {}).get('size', 0) or 0
            if file_size and file_size > self.max_file_size_mb * 1024 * 1024:
                msg = 'File too large: {} bytes exceeds {}MB limit'.format(file_size, self.max_file_size_mb)
                logger.error(msg)
                self._record_etl_error(item, 'size_check', msg, failed=True)
                return

            self._download_item(item)
            self._probe_tiff(item)

            png_item = self._build_and_upload_png(item)
            self._create_replace_modality(item, png_item)

            self._validate_dimensions(
                item=item,
                width=self.shape[-1],
                height=self.shape[-2],
                channels=self.shape[-3] if len(self.shape) == 3 else 1,
            )
            self._apply_legacy_metadata(item)

            if do_thumbnail:
                self._generate_thumbnail(item)

            exif_payload = self.exif_data if do_metadata else {'exif': {}, 'location': {}}
            item.metadata['system']['etl']['failed'] = False
            self._apply_image_etl_metadata(item, exif_payload, etl_failed=False)
            logger.info(
                'TIFF conversion complete: item=%s errors=%d mode=%s',
                item.id, len(item.metadata['system']['etl']['errors']), self.mode,
            )

        except Exception as e:
            logger.exception(
                'TIFF conversion failed: item=%s name=%s error_type=%s',
                item.id, item.name, type(e).__name__,
            )
            self._record_etl_error(
                item, 'conversion', str(e), failed=True,
                traceback=traceback.format_exc(),
            )

        finally:
            try:
                item.update(system_metadata=True)
            except Exception:
                logger.exception('Failed to flush system metadata item=%s', item.id)
            self._cleanup_files(self.tiff_filepath)

    # ------------------------------------------------------------------
    # Run-step helpers
    # ------------------------------------------------------------------

    def _download_item(self, item: dl.Item) -> None:
        """Download the TIFF to disk and store its path in ``self.tiff_filepath``."""
        self.tiff_filepath = item.download(overwrite=True)
        size_mb = (os.path.getsize(self.tiff_filepath) / (1024 * 1024)
                   if os.path.isfile(self.tiff_filepath) else -1)
        logger.info('Downloaded TIFF: item=%s name=%s path=%s size=%.2fMB',
                    item.id, item.name, self.tiff_filepath, size_mb)

    def _probe_tiff(self, item: dl.Item) -> None:
        """PIL-open the TIFF (lazy, header-only) and probe bit depth + EXIF.

        ``Image.open`` only reads the header — pixel data stays on disk until
        accessed. EXIF is fetched once and shared with the bit-depth probe.
        Results are stored on ``self`` (``pil_image``, ``is_multibit``,
        ``exif_data``).
        """
        # Lazy open: PIL reads ONLY the TIFF header here (a few KB).
        # Pixel data is NOT loaded into RAM — it stays on disk and is only
        # decoded on demand (e.g. when calling .load(), .convert(), .getdata(),
        # or iterating pixels). For huge TIFFs this keeps memory usage flat.
        try:
            self.pil_image = Image.open(self.tiff_filepath)
        except Exception as pil_err:
            logger.warning('PIL could not open file, using rasterio-only path: %s', pil_err)
            self._record_etl_error(item, 'pil_open', str(pil_err))
            self.pil_image = None
            self.is_multibit = True
            self.exif_data = {'exif': {}, 'location': {}}
            return

        logger.debug('PIL open: mode=%s size=%s (WxH) format=%s',
                     self.pil_image.mode, self.pil_image.size, self.pil_image.format)
        exifdata = self._read_exif_tags(item, self.pil_image)
        self.is_multibit = self._get_bits_per_sample(item, exifdata)
        self.exif_data = self._extract_exif(item, exifdata)

    def _read_exif_tags(self, item: dl.Item, pil_image: 'Image.Image'):
        """Read raw EXIF tags from a PIL image, returning None on failure."""
        try:
            return pil_image.getexif()
        except Exception as e:
            logger.warning('EXIF read failed: %s', e)
            self._record_etl_error(item, 'exif_read', str(e))
            return None

    def _build_and_upload_png(self, item: dl.Item) -> dl.Item:
        """Convert the TIFF to PNG in memory and upload it with originating-TIFF metadata.

        Stores ``shape``, ``tiff_meta`` and the converted PIL image on ``self``
        (as ``self.png_image``) so downstream consumers (thumbnail) can reuse
        it without a disk roundtrip.
        """
        if self.is_multibit:
            self.png_image, self.shape, self.tiff_meta = self._normalize_multibit(self.tiff_filepath)
            logger.info('Multibit conversion: size=%s mode=%s shape=%s',
                        self.png_image.size, self.png_image.mode, self.shape)
        else:
            self.png_image, self.shape, self.tiff_meta = self._convert_onebit(self.pil_image)
            logger.info('1-bit conversion: size=%s mode=%s shape=%s',
                        self.png_image.size, self.png_image.mode, self.shape)

        remote_path = os.path.dirname(item.filename)
        buf = BytesIO()
        self.png_image.save(buf, format='PNG')
        buf.seek(0)
        png_item = item.dataset.items.upload(
            local_path=buf,
            remote_path='/.dataloop/tiff-converter' + remote_path,
            remote_name='{}.png'.format(item.id),
        )
        if 'system' not in png_item.metadata:
            png_item.metadata['system'] = {}
        png_item.metadata['system']['tiff'] = {
            'originalItem': item.id,
            'tiffMetadata': self.tiff_meta,
        }
        png_item.update(system_metadata=True)
        return png_item

    @staticmethod
    def _create_replace_modality(item: dl.Item, png_item: dl.Item) -> None:
        item.modalities.create(
            name='png',
            ref=png_item.id,
            ref_type=dl.MODALITY_REF_TYPE_ID,
            modality_type='replace',
            timestamp=datetime.datetime.now().isoformat(),
        )

    def _apply_legacy_metadata(self, item: dl.Item) -> None:
        """Write legacy (top-level) system metadata fields for backward compat."""
        if 'system' not in item.metadata:
            item.metadata['system'] = {}
        item.metadata['system']['tiff'] = {
            'originalItem': item.id,
            'tiffMetadata': self.tiff_meta,
        }
        item.metadata['system']['height'] = self.dims['height']
        item.metadata['system']['width'] = self.dims['width']
        item.metadata['system']['channels'] = self.dims['channels']
        logger.info('Legacy metadata: width=%s height=%s channels=%s',
                    self.dims['width'], self.dims['height'], self.dims['channels'])

    def _apply_image_etl_metadata(self, item, exif_data, etl_failed: bool) -> None:
        """Write the Rubiks-aligned `imageEtl` block.

        Reads the current error list from ``item.metadata`` so callers don't
        have to pass it explicitly — it's maintained by ``_record_etl_error``.
        """
        etl_errors = item.metadata.get('system', {}).get('etl', {}).get('errors', [])
        item.metadata['system']['imageEtl'] = {
            'width': self.dims['width'],
            'height': self.dims['height'],
            'channels': self.dims['channels'],
            'exif': exif_data.get('exif', {}),
            'location': exif_data.get('location', {}),
            'etl': {
                'failed': etl_failed,
                'errors': etl_errors,
            },
        }

    @staticmethod
    def _record_etl_error(item, stage: str, error: str, failed: bool = False,
                          **extra) -> list:
        """Thin wrapper around ``common.etl_errors.record_etl_error``."""
        return record_etl_error(item, stage, error, failed=failed, **extra)

    # ------------------------------------------------------------------
    # Skip logic
    # ------------------------------------------------------------------

    def _should_skip(self, item: dl.Item) -> bool:
        if item.project_id in SKIP_PROJECTS:
            logger.info('Skipping item=%s: project %s in skip list', item.id, item.project_id)
            return True

        try:
            dataset = item.dataset
            if dataset.metadata.get('system', {}).get(SKIP_DATASET_FLAG, False):
                logger.info(
                    'Skipping item=%s: dataset %s has %s=true',
                    item.id, item.datasetId, SKIP_DATASET_FLAG
                )
                return True
        except Exception:
            pass  # if we can't check dataset metadata, proceed with conversion

        return False

    # ------------------------------------------------------------------
    # BitsPerSample detection
    # ------------------------------------------------------------------

    def _get_bits_per_sample(self, item: dl.Item, exifdata) -> bool:
        """Return True if multi-bit (needs geoio), False if 1-bit (PIL-only path)."""
        if exifdata is None:
            return True
        try:
            bits = exifdata.get(self.EXIF_TAG['BitsPerSample'])
            logger.debug('BitsPerSample = %s (type=%s)', bits, type(bits).__name__)
            if bits is not None:
                if isinstance(bits, tuple):
                    bits = bits[0]
                if int(bits) == 1:
                    logger.info('1-bit TIFF detected, using PIL conversion path')
                    return False
            logger.debug('Multi-bit path selected (bits=%s)', bits)
        except Exception as e:
            logger.warning('BitsPerSample extraction failed: %s', e)
            self._record_etl_error(item, 'exif_bits', str(e))
        # Default to multi-bit (geoio path) — safer fallback
        return True

    # ------------------------------------------------------------------
    # Conversion paths
    # ------------------------------------------------------------------

    def _normalize_multibit(self, tiff_path: str) -> tuple[Image.Image, tuple, dict]:
        """Normalize pixel values to uint8 using windowed (chunked) reads.

        Uses two-pass block-by-block streaming so the full raster is never
        materialised in memory. Only the first 3 bands are read for the PNG
        visualisation; the returned *shape* still reflects the original band
        count so that channels metadata stays accurate.
        """
        logger.info('Opening with rasterio: %s', tiff_path)

        with rasterio.open(tiff_path) as src:
            logger.info('rasterio src: %dx%d bands=%d dtype=%s crs=%s nodata=%s',
                        src.width, src.height, src.count, src.dtypes[0],
                        src.crs, src.nodata)

            full_shape = (src.count, src.height, src.width)
            vis_bands = min(src.count, 3)
            indexes = list(range(1, vis_bands + 1))  # rasterio is 1-indexed
            is_float = np.issubdtype(np.dtype(src.dtypes[0]), np.floating)

            meta = self._build_base_meta(src)
            meta = self._enrich_geo_metadata(src, meta, tiff_path)

            dmin, dmax = self._scan_global_minmax(src, indexes, is_float)
            output = self._normalize_windowed(src, indexes, is_float, dmin, dmax, vis_bands)

        result_image = self._array_to_image(output)
        meta = self._sanitize_metadata(meta)
        return result_image, full_shape, meta

    @staticmethod
    def _build_base_meta(src) -> dict:
        """Extract JSON-serializable base metadata from a rasterio source."""
        meta = dict(src.meta)
        # crs/transform are non-serializable; _enrich_geo_metadata re-adds them.
        meta.pop('crs', None)
        meta.pop('transform', None)
        if 'dtype' in meta:
            meta['dtype'] = str(meta['dtype'])
        return meta

    @staticmethod
    def _block_mask(block: np.ndarray, is_float: bool, nodata) -> np.ndarray:
        """Boolean mask of pixels to exclude (NaN/Inf/nodata)."""
        mask = np.zeros(block.shape, dtype=bool)
        if is_float:
            mask |= np.isnan(block) | np.isinf(block)
        if nodata is not None:
            mask |= (block == nodata)
        return mask

    def _scan_global_minmax(self, src, indexes, is_float) -> tuple[float, float]:
        """Pass 1: stream all blocks to compute the global valid-pixel min/max."""
        nodata = src.nodata
        gmin = np.float64(np.inf)
        gmax = np.float64(-np.inf)
        total_valid = 0
        total_masked = 0

        for _, window in src.block_windows(1):
            block = src.read(indexes=indexes, window=window)
            mask = self._block_mask(block, is_float, nodata)
            valid = block[~mask]
            total_valid += valid.size
            total_masked += int(mask.sum())
            if valid.size > 0:
                bmin, bmax = float(valid.min()), float(valid.max())
                if bmin < gmin:
                    gmin = bmin
                if bmax > gmax:
                    gmax = bmax

        if total_valid == 0:
            gmin = gmax = 0.0
        logger.info('Pass 1 min/max: dmin=%s dmax=%s valid=%d masked=%d',
                    gmin, gmax, total_valid, total_masked)
        return float(gmin), float(gmax)

    def _normalize_windowed(self, src, indexes, is_float, dmin, dmax,
                            vis_bands) -> np.ndarray:
        """Pass 2: windowed normalize source pixels into a uint8 (C,H,W) array."""
        nodata = src.nodata
        output = np.zeros((vis_bands, src.height, src.width), dtype=np.uint8)

        if dmax <= dmin:
            logger.warning('Flat image detected (min==max=%s); writing zero-filled output', dmin)
            return output

        scale = 255.0 / (dmax - dmin)
        logger.debug('Pass 2 normalize: range [%s, %s] -> [0, 255]', dmin, dmax)

        for _, window in src.block_windows(1):
            block = src.read(indexes=indexes, window=window)
            mask = self._block_mask(block, is_float, nodata)
            normalized = (((block.astype(np.float32) - dmin) * scale)
                          .clip(0, 255).astype(np.uint8))
            normalized[mask] = 0
            rs, cs = window.row_off, window.col_off
            output[:, rs:rs + window.height, cs:cs + window.width] = normalized

        return output

    @staticmethod
    def _array_to_image(output: np.ndarray) -> Image.Image:
        """Convert a (C,H,W) uint8 array to a PIL image (H,W) or (H,W,C)."""
        transposed = np.transpose(output, (1, 2, 0))
        squeezed = np.squeeze(transposed)
        image = Image.fromarray(squeezed)
        logger.info('Built PIL image: size=%s (WxH) mode=%s', image.size, image.mode)
        return image

    def _convert_onebit(self, pil_image: Image.Image) -> tuple[Image.Image, tuple, dict]:
        """Convert a 1-bit TIFF to RGBA using PIL only (no geoio needed)."""
        converted = pil_image.convert('RGBA')
        # Shape as (channels, height, width) to match geoio convention
        shape = (1, converted.size[1], converted.size[0])
        return converted, shape, {}

    @staticmethod
    def _sanitize_metadata(obj):
        """Recursively replace non-JSON-compliant floats (inf, -inf, nan) with None."""
        if isinstance(obj, dict):
            return {k: ServiceRunner._sanitize_metadata(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [ServiceRunner._sanitize_metadata(v) for v in obj]
        if isinstance(obj, float):
            if math.isinf(obj) or math.isnan(obj):
                return None
        return obj

    @staticmethod
    def _enrich_geo_metadata(src, meta: dict, tiff_path: str) -> dict:
        """Add geospatial fields to metadata dict from a rasterio dataset.

        Produces metadata matching the original GeoImage-based converter format.
        """
        # Capture driver before cleanup
        driver_name = meta.get('driver', 'GTiff')

        # Remove rasterio base fields not present in original GeoImage output
        for key in ('count', 'driver', 'dtype', 'height', 'width', 'nodata'):
            meta.pop(key, None)

        # Fields matching original GeoImage output
        meta['class_name'] = 'GeoImage'
        meta['driver_name'] = driver_name
        meta['file_name'] = tiff_path
        meta['file_list'] = [tiff_path]
        meta['shape'] = [src.count, src.width, src.height]
        meta['pixels'] = src.width * src.height

        # GDAL dtype info
        dtype_str = str(src.dtypes[0])
        gdal_code, gdal_name = GDAL_DTYPE_MAP.get(dtype_str, (0, dtype_str))
        meta['gdal_dtype'] = gdal_code
        meta['gdal_dtype_name'] = gdal_name

        # nodata duplicate field (original had both 'nodata' and 'no_data_value')
        if src.nodata is not None:
            meta['no_data_value'] = src.nodata

        try:
            crs_wkt = ''
            if src.crs:
                crs_wkt = src.crs.to_wkt()
                # Extract authority from WKT (matches original GeoImage behavior)
                authority = ServiceRunner._extract_authority_from_wkt(crs_wkt)
                if authority:
                    meta['authority'] = authority

            meta['projection_string'] = crs_wkt
            meta['pprint_proj_string'] = ServiceRunner._pretty_print_wkt(crs_wkt)

            if src.transform:
                # Convert rasterio Affine (a,b,c,d,e,f) to GDAL order (c,a,b,f,d,e)
                a, b, c, d, e, f = list(src.transform)[:6]
                meta['geo_transform'] = [c, a, b, f, d, e]
            if src.bounds:
                meta['extent'] = [
                    src.bounds.left,
                    src.bounds.top,
                    src.bounds.right,
                    src.bounds.bottom,
                ]
            if src.res:
                meta['resolution'] = [src.res[0], src.res[1]]
        except Exception:
            logger.warning('Failed to enrich geo metadata', exc_info=True)
        return meta

    @staticmethod
    def _extract_authority_from_wkt(wkt: str) -> str | None:
        """Extract authority from CRS WKT, matching original GeoImage behavior."""
        if not wkt:
            return None
        try:
            from osgeo import osr
            srs = osr.SpatialReference()
            if srs.ImportFromWkt(wkt) != 0:
                return None
            # Try root first, then progressively deeper targets
            for target in [None, 'GEOGCS', 'GEOGCS|DATUM', 'GEOGCS|DATUM|SPHEROID']:
                try:
                    auth_name = srs.GetAuthorityName(target)
                    auth_code = srs.GetAuthorityCode(target)
                    if auth_name and auth_code:
                        return '{}:{}'.format(auth_name, auth_code)
                except Exception:
                    continue
        except ImportError:
            logger.debug('osgeo not available, skipping authority extraction')
        except Exception:
            logger.warning('Failed to extract authority from WKT', exc_info=True)
        return None

    @staticmethod
    def _pretty_print_wkt(wkt: str) -> str:
        """Pretty-print CRS WKT matching original GeoImage format."""
        if not wkt:
            return ''
        try:
            from osgeo import osr
            srs = osr.SpatialReference()
            if srs.ImportFromWkt(wkt) == 0:
                return srs.ExportToPrettyWkt()
        except ImportError:
            logger.debug('osgeo not available, skipping WKT pretty-print')
        except Exception:
            logger.warning('Failed to pretty-print WKT', exc_info=True)
        return wkt

    # ------------------------------------------------------------------
    # EXIF extraction
    # ------------------------------------------------------------------

    def _extract_exif(self, item: dl.Item, exifdata) -> dict:
        """Extract EXIF metadata and GPS coordinates matching Rubiks field names."""
        result = {'exif': {}, 'location': {}}
        if not exifdata:
            return result
        try:
            tag_map = {
                'DateTimeOriginal': self.EXIF_TAG['DateTimeOriginal'],
                'Model':             self.EXIF_TAG['Model'],
                'ExposureTime':      self.EXIF_TAG['ExposureTime'],
                'FNumber':           self.EXIF_TAG['FNumber'],
                'ISO':               self.EXIF_TAG['ISO'],
                'WhiteBalance':      self.EXIF_TAG['WhiteBalance'],
                'Orientation':       self.EXIF_TAG['Orientation'],
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

            gps_ifd = exifdata.get_ifd(self.EXIF_TAG['GPSInfoIFD'])
            if gps_ifd:
                lat = self._parse_gps_coord(item, gps_ifd, 1, 2)
                lon = self._parse_gps_coord(item, gps_ifd, 3, 4)
                alt = gps_ifd.get(6)
                if lat is not None:
                    result['location']['latitude'] = lat
                if lon is not None:
                    result['location']['longitude'] = lon
                if alt is not None:
                    result['location']['altitude'] = float(alt)
        except Exception as e:
            logger.warning('EXIF extraction failed', exc_info=True)
            self._record_etl_error(item, 'exif', str(e))

        return result

    def _parse_gps_coord(self, item: dl.Item, gps_ifd: dict, ref_tag: int,
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
            self._record_etl_error(item, 'gps_coord', str(e))
        return None

    # ------------------------------------------------------------------
    # Dimension validation
    # ------------------------------------------------------------------

    def _validate_dimensions(self, item: dl.Item, width, height, channels) -> dict:
        """Validate extracted dimensions, clamp to INT32_MAX, and store on ``self.dims``."""
        if width is None or width <= 0:
            self._record_etl_error(item, 'dimensions', 'Invalid width: {}'.format(width))
        if height is None or height <= 0:
            self._record_etl_error(item, 'dimensions', 'Invalid height: {}'.format(height))
        if channels is None or channels <= 0:
            self._record_etl_error(item, 'dimensions', 'Invalid channels: {}'.format(channels))

        self.dims = {
            'width': self.clamp_int32(width) if width and width > 0 else None,
            'height': self.clamp_int32(height) if height and height > 0 else None,
            'channels': self.clamp_int32(channels) if channels and channels > 0 else None,
        }
        return self.dims

    # ------------------------------------------------------------------
    # Thumbnail generation
    # ------------------------------------------------------------------

    def _generate_thumbnail(self, item: dl.Item) -> tuple[bool, str | None]:
        """Generate and upload a thumbnail from the in-memory converted PNG.

        Uses ``self.png_image`` (already produced by ``_build_and_upload_png``) and
        uploads the resized image directly from a BytesIO buffer. Mutates
        ``item.metadata`` in place when successful.
        """
        try:
            buf = self._make_thumbnail_buffer(self.png_image)
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
            self._record_etl_error(item, 'thumbnail', 'Thumbnail generation failed')

    def _make_thumbnail_buffer(self, pil_image: Image.Image) -> BytesIO:
        """Resize ``pil_image`` in place and return a PNG-encoded BytesIO buffer."""
        thumb = pil_image
        if thumb.mode != 'RGBA':
            thumb = thumb.convert('RGBA')
        thumb.thumbnail(size=(self.default_thumb_size, self.default_thumb_size))
        buf = BytesIO()
        thumb.save(buf, format='PNG')
        buf.seek(0)
        return buf

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    @staticmethod
    def _cleanup_files(*filepaths):
        """Remove temporary files, logging warnings on failure."""
        for fp in filepaths:
            if fp and os.path.isfile(fp):
                try:
                    os.remove(fp)
                except OSError:
                    logger.warning('Failed to clean up temp file: %s', fp)

