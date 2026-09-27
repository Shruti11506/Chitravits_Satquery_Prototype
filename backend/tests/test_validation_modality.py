"""Modality validation (task brief section 5, 18)."""
import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.validation import modality_validator, raster_validator
from app.validation.errors import MODALITY_MISMATCH
from app.validation.schemas import RasterFacts


def _geotiff(*, count=1, dtype="uint16", descriptions=None, colorinterp=None):
    data = np.zeros((count, 20, 20), dtype=dtype)
    with MemoryFile() as mem:
        with mem.open(
            driver="GTiff", width=20, height=20, count=count, dtype=dtype,
            crs="EPSG:32643", transform=from_origin(0, 0, 10, 10),
        ) as dst:
            dst.write(data)
            for i, name in enumerate(descriptions or [], start=1):
                dst.set_band_description(i, name)
            if colorinterp:
                dst.colorinterp = colorinterp
        return mem.read()


def _jpeg_facts():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, format="JPEG")
    return raster_validator.extract_from_bytes(buf.getvalue(), "photo.jpg")


# ---- detection ----------------------------------------------------------------


def test_rgb_jpeg_is_detected_as_rgb():
    assert modality_validator.detect_modality(_jpeg_facts(), extension=".jpg", sensor=None, source=None, hint=None) == "rgb"


def test_sentinel2_style_multispectral_geotiff_is_detected():
    facts = raster_validator.extract_from_bytes(_geotiff(count=13, descriptions=["b1"] * 13), "s2.tif")
    assert modality_validator.detect_modality(facts, extension=".tif", sensor=None, source=None, hint=None) == "multispectral"


def test_sar_vv_geotiff_is_detected_from_band_description_not_filename():
    facts = raster_validator.extract_from_bytes(_geotiff(descriptions=["VV"]), "definitely_not_sar_in_name.tif")
    assert modality_validator.detect_modality(facts, extension=".tif", sensor=None, source=None, hint=None) == "sar"


def test_unnamed_bands_and_no_metadata_stay_unknown_rather_than_guessed():
    facts = raster_validator.extract_from_bytes(_geotiff(count=2), "scene.tif")  # 2 bands, no names
    assert modality_validator.detect_modality(facts, extension=".tif", sensor=None, source=None, hint=None) == "unknown"


def test_explicit_hint_is_trusted_verbatim():
    facts = raster_validator.extract_from_bytes(_geotiff(count=2), "scene.tif")
    assert modality_validator.detect_modality(facts, extension=".tif", sensor=None, source=None, hint="sar") == "sar"


def test_sensor_metadata_field_is_consulted_only_for_ambiguous_cases():
    # 1-band TIFF, no band name -- ambiguous by structure alone; the
    # structured `sensor` field (not a filename) breaks the tie.
    facts = raster_validator.extract_from_bytes(_geotiff(count=1), "scene.tif")
    assert modality_validator.detect_modality(facts, extension=".tif", sensor="Sentinel-1 GRD", source=None, hint=None) == "sar"


# ---- compatibility --------------------------------------------------------------


def test_rgb_satisfies_a_workflow_allowing_optical():
    assert modality_validator.modality_issues("rgb", ["optical", "rgb"], role="single", workflow_label="Visual VQA", input_label="x") == []


def test_rgb_is_rejected_for_a_sar_only_workflow():
    issues = modality_validator.modality_issues("rgb", ["sar"], role="single", workflow_label="SAR VV analysis", input_label="x")
    assert [i.code for i in issues] == [MODALITY_MISMATCH]


def test_no_restriction_accepts_anything_including_unknown():
    assert modality_validator.modality_issues("unknown", None, role="single", workflow_label="Visual VQA", input_label="x") == []


def test_unknown_modality_is_rejected_rather_than_guessed_when_required():
    issues = modality_validator.modality_issues("unknown", ["sar"], role="single", workflow_label="SAR VV analysis", input_label="x")
    assert [i.code for i in issues] == [MODALITY_MISMATCH]
    assert "could not be determined" in issues[0].message


def test_role_keyed_allowed_modalities_apply_per_role():
    allowed = {"optical": ["optical", "rgb"], "sar": ["sar"]}
    assert modality_validator.modality_issues("sar", allowed, role="sar", workflow_label="Optical + SAR", input_label="x") == []
    assert modality_validator.modality_issues("rgb", allowed, role="sar", workflow_label="Optical + SAR", input_label="x")[0].code == MODALITY_MISMATCH
