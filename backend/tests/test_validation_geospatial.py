"""Geospatial validation (task brief section 4, 18)."""
import numpy as np
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.validation import geospatial_validator, raster_validator
from app.validation.errors import CRS_MISSING, GEOREFERENCE_MISSING, INVALID_CRS
from app.validation.schemas import RasterFacts


def _geotiff(*, crs="EPSG:32643", width=32, height=32):
    data = np.zeros((1, height, width), dtype="uint8")
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=width, height=height, count=1, dtype="uint8", crs=crs, transform=from_origin(776000, 1440000, 10, 10)) as dst:
            dst.write(data)
        return mem.read()


def _plain_tiff(width=32, height=32):
    data = np.zeros((1, height, width), dtype="uint8")
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=width, height=height, count=1, dtype="uint8") as dst:
            dst.write(data)
        return mem.read()


def test_georeferenced_geotiff_passes_when_required():
    facts = raster_validator.extract_from_bytes(_geotiff(), "s.tif")
    assert geospatial_validator.geospatial_issues(facts, input_label="x", required=True, extension=".tif") == []


def test_not_required_skips_the_check_entirely_even_without_crs():
    facts = raster_validator.extract_from_bytes(_plain_tiff(), "s.tif")
    assert geospatial_validator.geospatial_issues(facts, input_label="x", required=False, extension=".tif") == []


def test_missing_crs_is_rejected_when_required():
    facts = raster_validator.extract_from_bytes(_plain_tiff(), "s.tif")
    issues = geospatial_validator.geospatial_issues(facts, input_label="x", required=True, extension=".tif")
    assert [i.code for i in issues] == [CRS_MISSING]


def test_missing_transform_is_rejected_when_required():
    # A CRS present but no transform is a structurally-incomplete case rasterio
    # itself won't produce -- test geospatial_validator's own logic directly.
    facts = RasterFacts(format="GeoTIFF", width=10, height=10, crs="EPSG:4326", transform=None, bounds=None)
    issues = geospatial_validator.geospatial_issues(facts, input_label="x", required=True, extension=".tif")
    assert [i.code for i in issues] == [GEOREFERENCE_MISSING]


def test_crs_that_cannot_be_reprojected_is_invalid():
    facts = RasterFacts(format="GeoTIFF", width=10, height=10, crs="a bogus crs string", transform=[1, 0, 0, 0, -1, 0], bounds=None)
    issues = geospatial_validator.geospatial_issues(facts, input_label="x", required=True, extension=".tif")
    assert [i.code for i in issues] == [INVALID_CRS]


def test_jpeg_png_are_never_georeferenced_even_if_required():
    facts = raster_validator.extract_from_bytes(_png_bytes(), "photo.png")
    issues = geospatial_validator.geospatial_issues(facts, input_label="x", required=True, extension=".png")
    assert [i.code for i in issues] == [GEOREFERENCE_MISSING]
    # And it never invents crs/bounds to satisfy the requirement.
    assert facts.crs is None and facts.bounds is None


def _png_bytes():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, format="PNG")
    return buf.getvalue()
