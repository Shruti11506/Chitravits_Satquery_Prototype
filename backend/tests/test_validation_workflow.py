"""Workflow compatibility -- the full pipeline via `validate_images`, exercising
the task brief's compatibility matrix (sections 7, 9, 11) end to end, without
any Supabase/HTTP involvement (see test_validation_api.py for that)."""
import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.validation.errors import (
    BAND_MISMATCH,
    BAND_MISSING,
    GEOREFERENCE_MISSING,
    IMAGE_COUNT_MISMATCH,
    MODALITY_MISMATCH,
    NOT_DISTINCT_OBSERVATIONS,
    RESOURCE_LIMIT_EXCEEDED,
    UNKNOWN_WORKFLOW,
    WORKFLOW_INPUT_MISMATCH,
)
from app.validation.schemas import ImageInput
from app.validation.service import validate_images
from tests.images import unique_color, unique_fill


def _geotiff(*, count=3, dtype="uint16", crs="EPSG:32643", width=64, height=48, descriptions=None):
    data = np.full((count, height, width), unique_fill(), dtype=dtype)
    with MemoryFile() as mem:
        with mem.open(
            driver="GTiff", width=width, height=height, count=count, dtype=dtype,
            crs=crs, transform=from_origin(776000, 1440000, 10, 10),
        ) as dst:
            dst.write(data)
            for i, name in enumerate(descriptions or [], start=1):
                dst.set_band_description(i, name)
        return mem.read()


def _jpeg(width=40, height=30):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=unique_color()).save(buf, format="JPEG")
    return buf.getvalue()


def _img(filename, content, *, role="single", modality_hint=None, imagery_id=None, sensor=None) -> ImageInput:
    return ImageInput(
        filename=filename, content_type=None, content=content, size_bytes=len(content),
        role=role, modality_hint=modality_hint, imagery_id=imagery_id or filename, sensor=sensor,
    )


_S2_BAND_NAMES = ["b01", "blue", "green", "red", "b05", "b06", "b07", "nir", "b8a", "b09", "b10", "swir1", "swir2"]
s2_multispectral = lambda: _img("s2.tif", _geotiff(count=13, descriptions=_S2_BAND_NAMES), imagery_id="s2")
rgb_jpeg = lambda: _img("photo.jpg", _jpeg(), imagery_id="rgb")
sar_vv = lambda role="single", imagery_id="vv": _img("s1.tif", _geotiff(count=1, descriptions=["VV"]), role=role, imagery_id=imagery_id)
sar_vh = lambda role="single", imagery_id="vh": _img("s1.tif", _geotiff(count=1, descriptions=["VH"]), role=role, imagery_id=imagery_id)
plain_geotiff = lambda: _img("geo.tif", _geotiff(count=3, descriptions=["red", "green", "blue"]), imagery_id="geo")


# ---- request-level -------------------------------------------------------------


def test_unknown_workflow_is_rejected():
    result = validate_images(workflow="not_a_real_workflow", images=[rgb_jpeg()])
    assert result.status == "REJECT"
    assert result.errors[0].code == UNKNOWN_WORKFLOW


def test_wrong_image_count_is_rejected():
    result = validate_images(workflow="visual_vqa", images=[rgb_jpeg(), rgb_jpeg()])
    assert result.status == "REJECT"
    assert any(e.code == IMAGE_COUNT_MISMATCH for e in result.errors)


def test_only_t1_for_a_bitemporal_workflow_is_rejected():
    result = validate_images(workflow="bitemporal_change", images=[_img("t1.tif", _geotiff(), role="t1")])
    assert result.status == "REJECT"
    assert any(e.code == IMAGE_COUNT_MISMATCH for e in result.errors)


def test_wrong_roles_for_a_two_image_workflow_is_rejected():
    result = validate_images(workflow="bitemporal_change", images=[
        _img("a.tif", _geotiff(), role="single", imagery_id="a"),
        _img("b.tif", _geotiff(), role="single", imagery_id="b"),
    ])
    assert result.status == "REJECT"
    assert any(e.code == WORKFLOW_INPUT_MISMATCH for e in result.errors)


def test_same_image_twice_is_not_distinct_observations():
    result = validate_images(workflow="bitemporal_change", images=[
        _img("a.tif", _geotiff(), role="t1", imagery_id="same-id"),
        _img("a.tif", _geotiff(), role="t2", imagery_id="same-id"),
    ])
    assert result.status == "REJECT"
    assert any(e.code == NOT_DISTINCT_OBSERVATIONS for e in result.errors)


def test_too_many_images_hits_the_resource_limit(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "VALIDATION_MAX_INPUT_IMAGES", 1)
    result = validate_images(workflow="bitemporal_change", images=[
        _img("a.tif", _geotiff(), role="t1", imagery_id="a"),
        _img("b.tif", _geotiff(), role="t2", imagery_id="b"),
    ])
    assert result.status == "REJECT"
    assert any(e.code == RESOURCE_LIMIT_EXCEEDED for e in result.errors)


def test_oversized_dimensions_hit_the_resource_limit(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "VALIDATION_MAX_IMAGE_WIDTH", 10)
    result = validate_images(workflow="visual_vqa", images=[rgb_jpeg()])
    assert result.status == "REJECT"
    assert any(e.code == RESOURCE_LIMIT_EXCEEDED for e in result.errors)


def test_too_many_bands_hit_the_resource_limit(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "VALIDATION_MAX_BANDS", 5)
    result = validate_images(workflow="ndvi", images=[s2_multispectral()])
    assert result.status == "REJECT"
    assert any(e.code == RESOURCE_LIMIT_EXCEEDED for e in result.errors)


# ---- the compatibility matrix (task brief section 9) ---------------------------


@pytest.mark.parametrize(
    "workflow,image_factory,expect_valid,expect_code",
    [
        ("ndvi", s2_multispectral, True, None),
        ("ndvi", rgb_jpeg, False, BAND_MISSING),
        ("visual_vqa", rgb_jpeg, True, None),
        ("visual_vqa", plain_geotiff, True, None),  # Visual VQA / GeoTIFF -> VALID
    ],
)
def test_single_image_matrix(workflow, image_factory, expect_valid, expect_code):
    result = validate_images(workflow=workflow, images=[image_factory()])
    assert result.valid is expect_valid
    if expect_code:
        assert any(e.code == expect_code for e in result.errors)


def test_sar_change_with_vv_both_times_is_valid():
    result = validate_images(workflow="bitemporal_change", images=[
        sar_vv(role="t1", imagery_id="t1"), sar_vv(role="t2", imagery_id="t2"),
    ])
    assert result.valid, result.errors


def test_sar_change_does_not_validate_polarisation():
    # Scope: no band/polarisation validation for Sentinel-1 / RISAT. A VV/VH
    # pair has the same band count and modality, so it passes validation.
    result = validate_images(workflow="bitemporal_change", images=[
        sar_vv(role="t1", imagery_id="t1"), sar_vh(role="t2", imagery_id="t2"),
    ])
    assert result.valid, result.errors


def test_optical_sar_with_both_present_is_valid():
    result = validate_images(workflow="optical_sar_analysis", images=[
        _img("opt.tif", _geotiff(count=3, descriptions=["red", "green", "blue"]), role="optical", imagery_id="opt"),
        _img("sar.tif", _geotiff(count=1, descriptions=["VV"]), role="sar", imagery_id="sar"),
    ])
    assert result.valid, result.errors


def test_optical_sar_with_only_optical_is_rejected():
    result = validate_images(workflow="optical_sar_analysis", images=[
        _img("opt.tif", _geotiff(count=3, descriptions=["red", "green", "blue"]), role="optical", imagery_id="opt"),
    ])
    assert result.valid is False
    assert any(e.code == IMAGE_COUNT_MISMATCH for e in result.errors)


def test_optical_sar_with_two_optical_images_is_rejected_by_role():
    result = validate_images(workflow="optical_sar_analysis", images=[
        _img("opt1.tif", _geotiff(count=3, descriptions=["red", "green", "blue"]), role="optical", imagery_id="a"),
        _img("opt2.tif", _geotiff(count=3, descriptions=["red", "green", "blue"]), role="optical", imagery_id="b"),
    ])
    assert result.valid is False
    assert any(e.code == WORKFLOW_INPUT_MISMATCH for e in result.errors)


# ---- the response always describes what was inspected --------------------------


def test_response_inputs_describe_every_image_valid_or_not():
    result = validate_images(workflow="ndvi", images=[rgb_jpeg()])
    assert len(result.inputs) == 1
    described = result.inputs[0]
    assert described.format == "JPEG"
    assert described.modality == "rgb"
    assert described.georeferenced is False
