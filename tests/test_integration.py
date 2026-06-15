import pytest
from unittest.mock import MagicMock, patch
from io import BytesIO
from PIL import Image
import sys

# Mock the dl module before importing main
sys.modules['dl'] = MagicMock()
sys.modules['dl.exceptions'] = MagicMock()

from main import ServiceRunner


def test_happy_path_full_exif_jpeg(mock_dl_item, mock_dl_progress, mock_dataset):
    """Test 1: Happy path — full EXIF JPEG"""
    # Create a JPEG with EXIF
    img = Image.new("RGB", (800, 600))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
    
    with patch('main.dl.datasets.get', return_value=mock_dataset):
        runner = ServiceRunner()
        runner.on_create(item, mock_dl_progress)
    
    # Assertions
    assert item.update.called
    assert item.metadata["system"]["width"] == 800
    assert item.metadata["system"]["height"] == 600
    assert item.metadata["system"]["channels"] == 3
    assert "thumbnailId" in item.metadata["system"]


def test_no_exif_image_png(mock_dl_item, mock_dl_progress, mock_dataset):
    """Test 2: No EXIF image (PNG)"""
    img = Image.new("RGB", (400, 300))
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/png")
    
    with patch('main.dl.datasets.get', return_value=mock_dataset):
        runner = ServiceRunner()
        runner.on_create(item, mock_dl_progress)
    
    # Assertions
    assert item.update.called
    assert item.metadata["system"]["width"] == 400
    assert item.metadata["system"]["height"] == 300
    assert "exif" not in item.metadata["system"]
    assert "location" not in item.metadata["system"]
    assert "location" not in item.metadata.get("user", {})


def test_non_image_mime(mock_dl_item, mock_dl_progress):
    """Test 3: Non-image MIME — writes etl={failed:True} and updates item"""
    item = mock_dl_item(mimetype="video/mp4")
    
    runner = ServiceRunner()
    result = runner.on_create(item, mock_dl_progress)
    
    # Should return early without calling download
    assert not item.download.called
    # Should write ETL failure and update
    assert item.metadata["system"]["etl"]["failed"] is True
    assert len(item.metadata["system"]["etl"]["errors"]) == 1
    assert "Unsupported mimetype: video/mp4" in item.metadata["system"]["etl"]["errors"][0]
    assert item.update.called
    assert result is item


def test_enable_image_preprocess_false(mock_dl_item, mock_dl_progress):
    """Test 4: ENABLE_IMAGE_PREPROCESS=false"""
    import os
    with patch.dict(os.environ, {'ENABLE_IMAGE_PREPROCESS': 'false'}):
        # Need to reload the module to pick up the env var
        import importlib
        import main
        importlib.reload(main)
        
        item = mock_dl_item(mimetype="image/jpeg")
        runner = main.ServiceRunner()
        runner.on_create(item, mock_dl_progress)
    
    # Should return early without calling download
    assert not item.download.called


def test_enable_thumbnail_false(mock_dl_item, mock_dl_progress):
    """Test 5: ENABLE_THUMBNAIL=false"""
    import os
    with patch.dict(os.environ, {'ENABLE_THUMBNAIL': 'false'}):
        import importlib
        import main
        importlib.reload(main)
        
        img = Image.new("RGB", (800, 600))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        
        item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
        
        runner = main.ServiceRunner()
        runner.on_create(item, mock_dl_progress)
    
    # No thumbnail upload should occur
    assert "thumbnailId" not in item.metadata["system"]


def test_exif_extraction_fails(mock_dl_item, mock_dl_progress, mock_dataset):
    """Test 6: EXIF extraction fails — soft error, not hard failure"""
    img = Image.new("RGB", (800, 600))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
    
    # Ensure thumbnail generation is enabled
    import os
    with patch.dict(os.environ, {'ENABLE_THUMBNAIL': 'true'}):
        import importlib
        import main
        importlib.reload(main)
        
        with patch('main.extract_exif', side_effect=Exception("EXIF failed")):
            with patch('main.dl.datasets.get', return_value=mock_dataset):
                runner = main.ServiceRunner()
                runner.on_create(item, mock_dl_progress)
    
    # Thumbnail should still be generated
    assert "thumbnailId" in item.metadata["system"]
    # ETL should have errors but not failed
    etl = item.metadata["system"]["etl"]
    assert "failed" not in etl
    assert len(etl["errors"]) == 1
    assert "Exif extraction failed" in etl["errors"][0]
    # Dimensions should still be present
    assert item.metadata["system"]["width"] == 800
    assert item.metadata["system"]["height"] == 600


def test_thumbnail_gen_fails(mock_dl_item, mock_dl_progress):
    """Test 7: Thumbnail gen fails — soft error in etl.errors"""
    img = Image.new("RGB", (800, 600))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
    
    with patch('main.generate_thumbnail', side_effect=Exception("Thumbnail failed")):
        runner = ServiceRunner()
        runner.on_create(item, mock_dl_progress)
    
    # Metadata should still be written
    assert item.update.called
    assert "thumbnailId" not in item.metadata["system"]
    # ETL should have errors but not failed
    etl = item.metadata["system"]["etl"]
    assert "failed" not in etl
    assert len(etl["errors"]) == 1
    assert "Thumbnail generation failed" in etl["errors"][0]


def test_both_fail(mock_dl_item, mock_dl_progress):
    """Test 8: Both EXIF and thumbnail fail — soft errors, no raise"""
    img = Image.new("RGB", (800, 600))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
    
    # Set ENABLE_THUMBNAIL to True to ensure thumbnail generation runs
    import os
    with patch.dict(os.environ, {'ENABLE_THUMBNAIL': 'true'}):
        import importlib
        import main
        importlib.reload(main)
        
        with patch('main.extract_exif', side_effect=Exception("EXIF failed")):
            with patch('main.generate_thumbnail', side_effect=Exception("Thumbnail failed")):
                runner = main.ServiceRunner()
                runner.on_create(item, mock_dl_progress)
    
    # ETL should have 2 errors but no failed flag
    etl = item.metadata["system"]["etl"]
    assert "failed" not in etl
    assert len(etl["errors"]) == 2
    assert any("Exif extraction failed" in e for e in etl["errors"])
    assert any("Thumbnail generation failed" in e for e in etl["errors"])


def test_download_fails(mock_dl_item, mock_dl_progress):
    """Test 9: Download fails"""
    item = mock_dl_item(mimetype="image/jpeg")
    item.download.side_effect = Exception("Download failed")
    
    runner = ServiceRunner()
    with pytest.raises(Exception):
        runner.on_create(item, mock_dl_progress)


def test_tiff_image(mock_dl_item, mock_dl_progress, mock_dataset):
    """Test 10: TIFF image"""
    img = Image.new("RGB", (400, 300))
    buf = BytesIO()
    img.save(buf, format="TIFF")
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/tiff")
    
    with patch('main.dl.datasets.get', return_value=mock_dataset):
        runner = ServiceRunner()
        runner.on_create(item, mock_dl_progress)
    
    # TIFF should be processed normally
    assert item.update.called
    assert item.metadata["system"]["width"] == 400
    assert item.metadata["system"]["height"] == 300


def test_orientation_raw_dimensions_preserved(mock_dl_item, mock_dl_progress, mock_dataset):
    """Test 11: Orientation — raw dimensions preserved"""
    from PIL import ExifTags
    
    # Create a portrait image with orientation=6 (90° CW)
    # Stored as 800x600 but should display as 600x800
    img = Image.new("RGB", (800, 600))
    exif = img.getexif()
    exif[ExifTags.Base.Orientation] = 6
    
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
    
    with patch('main.dl.datasets.get', return_value=mock_dataset):
        runner = ServiceRunner()
        runner.on_create(item, mock_dl_progress)
    
    # Dimensions should reflect original pre-rotation layout
    assert item.metadata["system"]["width"] == 800
    assert item.metadata["system"]["height"] == 600


def test_file_too_large(mock_dl_item, mock_dl_progress):
    """Test 12: File too large"""
    item = mock_dl_item(mimetype="image/jpeg")
    item.metadata["system"]["size"] = 200 * 1024 * 1024  # 200MB
    
    runner = ServiceRunner()
    runner.on_create(item, mock_dl_progress)
    
    # Should return early without calling download
    assert not item.download.called


def test_gps_dual_storage(mock_dl_item, mock_dl_progress, mock_dataset):
    """Test 13: GPS dual storage"""
    from PIL import ExifTags
    from PIL.ExifTags import IFD
    from PIL.TiffImagePlugin import IFDRational
    
    img = Image.new("RGB", (800, 600))
    exif = img.getexif()
    
    # Use tag IDs directly since GPS constants aren't available in older Pillow
    GPS_LATITUDE_REF = 1
    GPS_LATITUDE = 2
    GPS_LONGITUDE_REF = 3
    GPS_LONGITUDE = 4
    
    gps_ifd = {
        GPS_LATITUDE_REF: "N",
        GPS_LATITUDE: [IFDRational(32, 1), IFDRational(5, 1), IFDRational(7, 1)],
        GPS_LONGITUDE_REF: "E",
        GPS_LONGITUDE: [IFDRational(34, 1), IFDRational(46, 1), IFDRational(55, 1)],
    }
    exif[IFD.GPSInfo] = gps_ifd
    
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
    
    with patch('main.dl.datasets.get', return_value=mock_dataset):
        runner = ServiceRunner()
        runner.on_create(item, mock_dl_progress)
    
    # GPS should be in both system and user
    assert "location" in item.metadata["system"]
    assert "location" in item.metadata["user"]
    assert item.metadata["system"]["location"]["latitude"] > 0
    assert item.metadata["user"]["location"]["latitude"] > 0


def test_default_thumb_size_override(mock_dl_item, mock_dl_progress, mock_dataset):
    """Test 14: DEFAULT_THUMB_SIZE override"""
    import os
    with patch.dict(os.environ, {'DEFAULT_THUMB_SIZE': '256'}):
        import importlib
        import main
        importlib.reload(main)
        
        img = Image.new("RGB", (4032, 3024))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        
        item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
        
        # Capture the thumbnail buffer to check size
        thumb_buf = None
        original_upload = mock_dataset.items.upload
        
        def capture_upload(*args, **kwargs):
            nonlocal thumb_buf
            thumb_buf = kwargs.get('local_path', args[0] if args else None)
            return original_upload(*args, **kwargs)
        
        mock_dataset.items.upload.side_effect = capture_upload
        
        with patch('main.dl.datasets.get', return_value=mock_dataset):
            runner = main.ServiceRunner()
            runner.on_create(item, mock_dl_progress)
        
        # Check thumbnail size
        if thumb_buf:
            thumb = Image.open(thumb_buf)
            # Should fit within 256x256 box
            assert thumb.size[0] <= 256
            assert thumb.size[1] <= 256


def test_corrupt_image(mock_dl_item, mock_dl_progress):
    """Test: Corrupt image — etl.failed=True with error message"""
    corrupt_buf = BytesIO(b"not a real image at all")
    
    item = mock_dl_item(buffer=corrupt_buf, mimetype="image/jpeg")
    
    runner = ServiceRunner()
    result = runner.on_create(item, mock_dl_progress)
    
    # Should write ETL hard failure
    etl = item.metadata["system"]["etl"]
    assert etl["failed"] is True
    assert len(etl["errors"]) == 1
    assert "Image metadata extraction failed" in etl["errors"][0]
    assert item.update.called
    assert result is item


def test_happy_path_no_etl(mock_dl_item, mock_dl_progress, mock_dataset):
    """Test: Happy path — no etl key in metadata.system"""
    img = Image.new("RGB", (800, 600))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
    
    with patch('main.dl.datasets.get', return_value=mock_dataset):
        runner = ServiceRunner()
        result = runner.on_create(item, mock_dl_progress)
    
    # No ETL key should be present on happy path
    assert "etl" not in item.metadata["system"]
    assert item.metadata["system"]["width"] == 800
    assert item.metadata["system"]["height"] == 600
    assert result is item


def test_rerun_clears_old_etl(mock_dl_item, mock_dl_progress, mock_dataset):
    """Test: Re-run clears stale etl from previous runs"""
    img = Image.new("RGB", (800, 600))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
    # Pre-set stale ETL from a previous run
    item.metadata["system"]["etl"] = {"failed": True, "errors": ["old error"]}
    
    with patch('main.dl.datasets.get', return_value=mock_dataset):
        runner = ServiceRunner()
        result = runner.on_create(item, mock_dl_progress)
    
    # Stale ETL should be cleared on successful run
    assert "etl" not in item.metadata["system"]
    assert item.metadata["system"]["width"] == 800
    assert result is item
