"""File validation + raster/image structure extraction (task brief sections 2, 3, 18)."""
import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.validation import file_validator, raster_validator
from app.validation.errors import FILE_CORRUPTED, FILE_TOO_LARGE, INVALID_DIMENSIONS, UNSUPPORTED_FORMAT
from app.validation.schemas import ImageInput


def _geotiff(*, count=3, dtype="uint16", crs="EPSG:32643", width=64, height=48, descriptions=None):
    rng = np.random.default_rng(0)
    data = rng.integers(100, 4000, size=(count, height, width)).astype(dtype)
    with MemoryFile() as mem:
        with mem.open(
            driver="GTiff", width=width, height=height, count=count, dtype=dtype,
            crs=crs, transform=from_origin(776000, 1440000, 10, 10),
        ) as dst:
            dst.write(data)
            for i, name in enumerate(descriptions or [], start=1):
                dst.set_band_description(i, name)
        return mem.read()


def _plain_tiff(*, width=32, height=32):
    """A TIFF with no CRS at all -- still a perfectly valid raster."""
    data = np.zeros((1, height, width), dtype="uint8")
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=width, height=height, count=1, dtype="uint8") as dst:
            dst.write(data)
        return mem.read()


def _jpeg(*, width=40, height=30, mode="RGB"):
    import io
    buf = io.BytesIO()
    Image.new(mode, (width, height), color=(10, 20, 30) if mode == "RGB" else 128).save(buf, format="JPEG")
    return buf.getvalue()


def _png(*, width=40, height=30):
    import io
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(5, 5, 5)).save(buf, format="PNG")
    return buf.getvalue()


def _image(filename: str, content: bytes, **kwargs) -> ImageInput:
    return ImageInput(filename=filename, content_type=None, content=content, size_bytes=len(content), **kwargs)


# ---- format_issues (section 2) -----------------------------------------------


def test_valid_geotiff_passes_format_check():
    assert file_validator.format_issues(_image("scene.tif", _geotiff())) == []


def test_valid_jpeg_passes_format_check():
    assert file_validator.format_issues(_image("photo.jpg", _jpeg())) == []


def test_valid_png_passes_format_check():
    assert file_validator.format_issues(_image("photo.png", _png())) == []


@pytest.mark.parametrize("filename", ["document.pdf", "unknown.exe", "scene.bmp"])
def test_unsupported_extension_is_rejected(filename):
    issues = file_validator.format_issues(_image(filename, b"whatever bytes"))
    assert [i.code for i in issues] == [UNSUPPORTED_FORMAT]


def test_content_not_matching_extension_is_rejected_before_opening():
    # A text file renamed to .tif: wrong magic bytes, caught without ever
    # handing it to rasterio.
    issues = file_validator.format_issues(_image("scene.tif", b"not actually a tiff"))
    assert [i.code for i in issues] == [FILE_CORRUPTED]


def test_oversized_file_is_rejected(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "MAX_UPLOAD_SIZE_MB", 0)
    issues = file_validator.format_issues(_image("scene.tif", _geotiff()))
    assert [i.code for i in issues] == [FILE_TOO_LARGE]


# ---- raster_validator (section 3) --------------------------------------------


def test_geotiff_structure_is_extracted():
    facts = raster_validator.extract_from_bytes(_geotiff(count=13, descriptions=["b1"] * 13), "s2.tif")
    assert facts.format == "GeoTIFF"
    assert facts.width == 64 and facts.height == 48
    assert facts.band_count == 13
    assert facts.georeferenced is True
    assert facts.crs and "32643" in facts.crs
    assert facts.error is None


def test_plain_tiff_without_crs_is_still_readable():
    facts = raster_validator.extract_from_bytes(_plain_tiff(), "scan.tif")
    assert facts.format == "TIFF"
    assert facts.georeferenced is False
    assert facts.crs is None
    assert facts.error is None


def test_jpeg_structure_is_extracted_via_pillow():
    facts = raster_validator.extract_from_bytes(_jpeg(width=100, height=80), "photo.jpg")
    assert facts.format == "JPEG"
    assert facts.width == 100 and facts.height == 80
    assert facts.band_count == 3
    assert facts.georeferenced is False
    assert facts.error is None


def test_png_structure_is_extracted_via_pillow():
    facts = raster_validator.extract_from_bytes(_png(), "photo.png")
    assert facts.format == "PNG"
    assert facts.error is None


def test_corrupted_tiff_is_rejected():
    truncated = _geotiff()[:200]  # a real TIFF header, but truncated pixel data
    facts = raster_validator.extract_from_bytes(truncated, "broken.tif")
    assert facts.error is not None


def test_corrupted_jpeg_is_rejected():
    truncated = _jpeg()[:20]
    facts = raster_validator.extract_from_bytes(truncated, "broken.jpg")
    assert facts.error is not None


def test_structure_issues_reports_file_corrupted_for_an_error():
    facts = raster_validator.extract_from_bytes(b"garbage", "broken.tif")
    issues = raster_validator.structure_issues(facts, input_label="x")
    assert [i.code for i in issues] == [FILE_CORRUPTED]


def test_structure_issues_reports_invalid_dimensions_for_zero_size():
    from app.validation.schemas import RasterFacts
    facts = RasterFacts(format="GeoTIFF", width=0, height=0)
    issues = raster_validator.structure_issues(facts, input_label="x")
    assert [i.code for i in issues] == [INVALID_DIMENSIONS]


def test_known_properties_reproduce_bytes_derived_facts():
    """facts_from_known_properties (the no-re-download path) must agree with
    extract_from_bytes for the same file -- see raster_service.py's own
    `_properties()`, which is what actually populates this dict at upload time."""
    from app.services.raster_service import _properties  # the real producer of this dict

    content = _geotiff(count=4, descriptions=["red", "green", "blue", "nir"])
    with rasterio.io.MemoryFile(content) as mem, mem.open() as src:
        properties = _properties(src)

    from_bytes = raster_validator.extract_from_bytes(content, "s2.tif")
    from_properties = raster_validator.facts_from_known_properties(properties)
    assert from_properties.width == from_bytes.width
    assert from_properties.band_count == from_bytes.band_count
    assert from_properties.crs == from_bytes.crs
    assert from_properties.band_descriptions == from_bytes.band_descriptions
