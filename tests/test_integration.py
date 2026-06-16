from unittest.mock import MagicMock, patch
from io import BytesIO
from PIL import Image
import sys

# Mock the dl module before importing main
sys.modules['dl'] = MagicMock()
sys.modules['dl.exceptions'] = MagicMock()

from main import ServiceRunner


def test_happy_path_full_exif_jpeg(mock_dl_item, mock_dl_progress):
    """Test 1: Happy path — full EXIF JPEG"""
    img = Image.new("RGB", (800, 600))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
    
    with patch.object(ServiceRunner, 'create_and_upload_thumbnail') as mock_thumb:
        mock_thumb.side_effect = lambda img, it, sz: it.metadata.setdefault("system", {}).__setitem__("thumbnailId", "thumb-123")
        runner = ServiceRunner()
        runner.run(item, progress=mock_dl_progress)
    
    assert item.update.called
    assert item.metadata["system"]["width"] == 800
    assert item.metadata["system"]["height"] == 600
    assert item.metadata["system"]["channels"] == 3
    assert "thumbnailId" in item.metadata["system"]


def test_no_exif_image_png(mock_dl_item, mock_dl_progress):
    """Test 2: No EXIF image (PNG)"""
    img = Image.new("RGB", (400, 300))
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/png")
    
    with patch.object(ServiceRunner, 'create_and_upload_thumbnail'):
        runner = ServiceRunner()
        runner.run(item, progress=mock_dl_progress)
    
    assert item.update.called
    assert item.metadata["system"]["width"] == 400
    assert item.metadata["system"]["height"] == 300
    assert "exif" not in item.metadata["system"]
    assert "location" not in item.metadata["system"]
    assert "location" not in item.metadata.get("user", {})


def test_non_image_mime(mock_dl_item, mock_dl_progress):
    """Test 3: Non-image MIME — raises and writes etl={failed:True}"""
    import pytest
    item = mock_dl_item(mimetype="video/mp4")

    runner = ServiceRunner()
    with pytest.raises(ValueError):
        runner.run(item, progress=mock_dl_progress)

    # Should not have attempted download
    assert not item.download.called
    # Should write ETL failure and update
    assert item.metadata["system"]["etl"]["failed"] is True
    assert len(item.metadata["system"]["etl"]["errors"]) == 1
    assert "Unsupported mimetype: video/mp4" in item.metadata["system"]["etl"]["errors"][0]["error"]
    assert item.update.called


def test_both_extract_flags_false_skips(mock_dl_item, mock_dl_progress):
    """Test 4: extract_metadata=False and extract_thumbnail=False -> skip"""
    item = mock_dl_item(mimetype="image/jpeg")
    context = MagicMock()
    context.trigger_input = {"extract_metadata": False, "extract_thumbnail": False}

    runner = ServiceRunner()
    result = runner.run(item, context=context, progress=mock_dl_progress)

    # Should return early without calling download
    assert not item.download.called
    assert result is item


def test_extract_thumbnail_false_skips_thumbnail(mock_dl_item, mock_dl_progress):
    """Test 5: extract_thumbnail=False skips thumbnail generation"""
    img = Image.new("RGB", (800, 600))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)

    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")

    context = MagicMock()
    context.trigger_input = {"extract_thumbnail": False}

    runner = ServiceRunner()
    runner.run(item, context=context, progress=mock_dl_progress)

    # No thumbnail should be generated
    assert "thumbnailId" not in item.metadata["system"]
    # But dimensions should still be present
    assert item.metadata["system"]["width"] == 800
    assert item.metadata["system"]["height"] == 600


def test_exif_extraction_fails(mock_dl_item, mock_dl_progress):
    """Test 6: EXIF extraction fails — soft error, not hard failure"""
    img = Image.new("RGB", (800, 600))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
    
    with patch.object(ServiceRunner, 'extract_exif', side_effect=Exception("EXIF failed")):
        with patch.object(ServiceRunner, 'create_and_upload_thumbnail') as mock_thumb:
            mock_thumb.side_effect = lambda img, it, sz: it.metadata.setdefault("system", {}).__setitem__("thumbnailId", "thumb-123")
            runner = ServiceRunner()
            runner.run(item, progress=mock_dl_progress)
    
    # Thumbnail should still be generated
    assert "thumbnailId" in item.metadata["system"]
    # ETL should have errors but not failed
    etl = item.metadata["system"]["etl"]
    assert "failed" not in etl
    assert len(etl["errors"]) == 1
    assert "Exif extraction failed" in etl["errors"][0]["error"]
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
    
    with patch.object(ServiceRunner, 'create_and_upload_thumbnail', side_effect=Exception("Thumbnail failed")):
        runner = ServiceRunner()
        runner.run(item, progress=mock_dl_progress)
    
    # Metadata should still be written
    assert item.update.called
    assert "thumbnailId" not in item.metadata["system"]
    # ETL should have errors but not failed
    etl = item.metadata["system"]["etl"]
    assert "failed" not in etl
    assert len(etl["errors"]) == 1
    assert "Thumbnail generation failed" in etl["errors"][0]["error"]


def test_both_fail(mock_dl_item, mock_dl_progress):
    """Test 8: Both EXIF and thumbnail fail — soft errors, no raise"""
    img = Image.new("RGB", (800, 600))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
    
    with patch.object(ServiceRunner, 'extract_exif', side_effect=Exception("EXIF failed")):
        with patch.object(ServiceRunner, 'create_and_upload_thumbnail', side_effect=Exception("Thumbnail failed")):
            runner = ServiceRunner()
            runner.run(item, progress=mock_dl_progress)
    
    # ETL should have 2 errors but no failed flag
    etl = item.metadata["system"]["etl"]
    assert "failed" not in etl
    assert len(etl["errors"]) == 2
    assert any("Exif extraction failed" in e["error"] for e in etl["errors"])
    assert any("Thumbnail generation failed" in e["error"] for e in etl["errors"])


def test_download_fails(mock_dl_item, mock_dl_progress):
    """Test 9: Download fails — raises, writes ETL error"""
    import pytest
    item = mock_dl_item(mimetype="image/jpeg")
    item.download.side_effect = Exception("Download failed")

    runner = ServiceRunner()
    with pytest.raises(Exception, match="Download failed"):
        runner.run(item, progress=mock_dl_progress)

    etl = item.metadata["system"]["etl"]
    assert etl["failed"] is True
    assert any("Download failed" in e["error"] for e in etl["errors"])
    assert item.update.called


def test_tiff_image(mock_dl_item, mock_dl_progress):
    """Test 10: TIFF image"""
    img = Image.new("RGB", (400, 300))
    buf = BytesIO()
    img.save(buf, format="TIFF")
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/tiff")
    
    with patch.object(ServiceRunner, 'create_and_upload_thumbnail'):
        runner = ServiceRunner()
        runner.run(item, progress=mock_dl_progress)
    
    assert item.update.called
    assert item.metadata["system"]["width"] == 400
    assert item.metadata["system"]["height"] == 300


def test_orientation_raw_dimensions_preserved(mock_dl_item, mock_dl_progress):
    """Test 11: Orientation — raw dimensions preserved"""
    from PIL import ExifTags
    
    # Stored as 800x600 but should display as 600x800 with orientation=6
    img = Image.new("RGB", (800, 600))
    exif = img.getexif()
    exif[ExifTags.Base.Orientation] = 6
    
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
    
    with patch.object(ServiceRunner, 'create_and_upload_thumbnail'):
        runner = ServiceRunner()
        runner.run(item, progress=mock_dl_progress)
    
    # Dimensions should reflect original pre-rotation layout
    assert item.metadata["system"]["width"] == 800
    assert item.metadata["system"]["height"] == 600


def test_file_too_large(mock_dl_item, mock_dl_progress):
    """Test 12: File too large — raises, writes ETL error"""
    import pytest
    item = mock_dl_item(mimetype="image/jpeg")
    item.metadata["system"]["size"] = 200 * 1024 * 1024  # 200MB

    runner = ServiceRunner()
    with pytest.raises(ValueError, match="File too large"):
        runner.run(item, progress=mock_dl_progress)

    assert not item.download.called
    etl = item.metadata["system"]["etl"]
    assert etl["failed"] is True
    assert any("File too large" in e["error"] for e in etl["errors"])
    assert item.update.called


def test_gps_dual_storage(mock_dl_item, mock_dl_progress):
    """Test 13: GPS dual storage"""
    from PIL import ExifTags
    from PIL.ExifTags import IFD
    from PIL.TiffImagePlugin import IFDRational
    
    img = Image.new("RGB", (800, 600))
    exif = img.getexif()
    
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
    
    with patch.object(ServiceRunner, 'create_and_upload_thumbnail'):
        runner = ServiceRunner()
        runner.run(item, progress=mock_dl_progress)
    
    # GPS should be in both system and user
    assert "location" in item.metadata["system"]
    assert "location" in item.metadata["user"]
    assert item.metadata["system"]["location"]["latitude"] > 0
    assert item.metadata["user"]["location"]["latitude"] > 0


def test_default_thumb_size_override(mock_dl_item, mock_dl_progress):
    """Test 14: default_thumb_size from trigger_input is forwarded to thumbnail"""
    img = Image.new("RGB", (4032, 3024))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)

    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")

    context = MagicMock()
    context.trigger_input = {"default_thumb_size": 256}

    with patch.object(ServiceRunner, 'create_and_upload_thumbnail') as mock_thumb:
        runner = ServiceRunner()
        runner.run(item, context=context, progress=mock_dl_progress)

    mock_thumb.assert_called_once()
    assert mock_thumb.call_args[0][2] == 256


def test_corrupt_image(mock_dl_item, mock_dl_progress):
    """Test: Corrupt image — raises, etl.failed=True with error message"""
    import pytest
    corrupt_buf = BytesIO(b"not a real image at all")

    item = mock_dl_item(buffer=corrupt_buf, mimetype="image/jpeg")

    runner = ServiceRunner()
    with pytest.raises(Exception):
        runner.run(item, progress=mock_dl_progress)

    # Should write ETL hard failure
    etl = item.metadata["system"]["etl"]
    assert etl["failed"] is True
    assert len(etl["errors"]) == 1
    assert "Failed to download/open image" in etl["errors"][0]["error"]
    assert item.update.called


def test_happy_path_no_etl(mock_dl_item, mock_dl_progress):
    """Test: Happy path — no etl key in metadata.system"""
    img = Image.new("RGB", (800, 600))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
    
    with patch.object(ServiceRunner, 'create_and_upload_thumbnail'):
        runner = ServiceRunner()
        result = runner.run(item, progress=mock_dl_progress)
    
    etl = item.metadata["system"].get("etl", {})
    assert "failed" not in etl
    assert etl.get("errors", []) == []
    assert item.metadata["system"]["width"] == 800
    assert item.metadata["system"]["height"] == 600
    assert result is item


def test_rerun_clears_old_etl(mock_dl_item, mock_dl_progress):
    """Test: Re-run clears stale etl from previous runs"""
    img = Image.new("RGB", (800, 600))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    
    item = mock_dl_item(buffer=buf, mimetype="image/jpeg")
    item.metadata["system"]["etl"] = {"failed": True, "errors": ["old error"]}
    
    with patch.object(ServiceRunner, 'create_and_upload_thumbnail'):
        runner = ServiceRunner()
        result = runner.run(item, progress=mock_dl_progress)
    
    etl = item.metadata["system"].get("etl", {})
    assert "failed" not in etl
    assert etl.get("errors", []) == []
    assert item.metadata["system"]["width"] == 800
    assert result is item
