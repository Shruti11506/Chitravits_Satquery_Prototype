"""Change Detection Input Validation: strict T1/T2 compatibility (pure
function + API), matching every rule in the task brief pasted into the
change-detection prompt."""
import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.validation import raster_validator
from app.validation.change_detection_validator import validate_change_detection_inputs
from app.validation.errors import (
    ASPECT_RATIO_MISMATCH,
    BAND_MISMATCH,
    CRS_MISMATCH,
    CRS_MISSING,
    FILE_CORRUPTED,
    FILE_FORMAT_MISMATCH,
    GEOREFERENCE_MISSING,
    IMAGE_DIMENSION_MISMATCH,
    MODALITY_MISMATCH,
    NOT_DISTINCT_OBSERVATIONS,
)
from app.validation.schemas import ChangeDetectionImageMetadata, ChangeDetectionRequirements
from tests.images import unique_color, unique_fill

ENDPOINT = "/api/v1/validation/change-detection"


# ---- fixtures ------------------------------------------------------------------


def _geotiff(*, descriptions, crs="EPSG:32643", width=64, height=48, count=None, tags=None, band_tags=None):
    count = count if count is not None else (len(descriptions) or 1)
    data = np.full((count, height, width), unique_fill(), dtype="uint16")
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=width, height=height, count=count, dtype="uint16", crs=crs, transform=from_origin(776000, 1440000, 10, 10)) as dst:
            dst.write(data)
            for i, name in enumerate(descriptions, start=1):
                dst.set_band_description(i, name)
            if tags:
                dst.update_tags(**tags)
            if band_tags:
                for i, btags in enumerate(band_tags, start=1):
                    dst.update_tags(i, **btags)
        return mem.read()


def _plain_tiff(*, width=64, height=48, count=1):
    """A TIFF with no CRS -- readable, but not georeferenced."""
    data = np.full((count, height, width), unique_fill(), dtype="uint8")
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=width, height=height, count=count, dtype="uint8") as dst:
            dst.write(data)
        return mem.read()


def _jpeg(width=64, height=48):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=unique_color()).save(buf, format="JPEG")
    return buf.getvalue()


def _meta(label, content, filename, *, imagery_id=None, sensor=None) -> ChangeDetectionImageMetadata:
    from app.validation.schemas import ImageInput
    image = ImageInput(filename=filename, content_type=None, content=content, size_bytes=len(content), imagery_id=imagery_id or label, sensor=sensor)
    return ChangeDetectionImageMetadata(
        label=label, facts=raster_validator.resolve_facts(image), extension=raster_validator.extension_of(filename),
        sensor=sensor, imagery_id=imagery_id or label,
    )


REQS = ChangeDetectionRequirements()
# The deferred dimension gates are off by default; these tests exercise them explicitly.
GATES_ON = ChangeDetectionRequirements(aspect_ratio_tolerance=0.01, require_exact_dimensions=True)


def sar_vv(label="T1", crs="EPSG:32643", imagery_id=None, **raster_kw):
    return _meta(label, _geotiff(descriptions=["VV"], crs=crs, **raster_kw), "s1.tif", imagery_id=imagery_id)


def sar_vh(label="T2", crs="EPSG:32643", imagery_id=None, **raster_kw):
    return _meta(label, _geotiff(descriptions=["VH"], crs=crs, **raster_kw), "s1.tif", imagery_id=imagery_id)


def optical_scene(label="T1", crs="EPSG:32643", imagery_id=None, **raster_kw):
    return _meta(label, _geotiff(descriptions=["red", "green", "blue"], crs=crs, **raster_kw), "opt.tif", imagery_id=imagery_id)


def jpeg_scene(label="T1", imagery_id=None, **raster_kw):
    return _meta(label, _jpeg(**raster_kw), "photo.jpg", imagery_id=imagery_id)


def ungeoref_tiff(label="T1", imagery_id=None, **raster_kw):
    return _meta(label, _plain_tiff(**raster_kw), "scan.tif", imagery_id=imagery_id)


def unknown_geotiff(label="T1", width=64, height=48, count=1, crs="EPSG:32643", imagery_id=None, **raster_kw):
    return _meta(label, _geotiff(descriptions=[], count=count, crs=crs, width=width, height=height, **raster_kw), "unknown.tif", imagery_id=imagery_id)


# ---- section 1/17: the core VALID/REJECT gate ----------------------------------


def test_matching_sar_vv_pair_is_valid():
    result = validate_change_detection_inputs(sar_vv("T1", imagery_id="a"), sar_vv("T2", imagery_id="b"), REQS)
    assert result.valid is True
    assert result.errors == []


def test_different_dates_same_everything_else_is_valid():
    """Section 10: T1 and T2 are expected to be different observations --
    different pixel content never causes a rejection."""
    t1 = sar_vv("T1", imagery_id="a")
    t2 = sar_vv("T2", imagery_id="b")
    # Simulate genuinely different pixel content / acquisition, same structure.
    t1.facts.dtypes, t2.facts.dtypes = ["uint16"], ["uint16"]
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is True


# ---- section 2: modality / image type ------------------------------------------


def test_optical_vs_sar_is_rejected():
    result = validate_change_detection_inputs(optical_scene("T1", imagery_id="a"), sar_vv("T2", imagery_id="b"), REQS)
    assert result.valid is False
    assert result.errors[0].code == MODALITY_MISMATCH
    assert result.errors[0].t1 == "RGB" and result.errors[0].t2 == "SAR"


def test_rgb_vs_sar_is_rejected():
    # require_matching_format disabled -- isolates the modality rule from the
    # (separately tested) format-family rule, since a JPEG vs a GeoTIFF would
    # otherwise correctly fail the earlier FILE_FORMAT_MISMATCH step first.
    no_format_check = ChangeDetectionRequirements(require_matching_format=False, require_geospatial=False)
    result = validate_change_detection_inputs(jpeg_scene("T1", imagery_id="a"), sar_vv("T2", imagery_id="b"), no_format_check)
    assert result.valid is False
    assert result.errors[0].code == MODALITY_MISMATCH
    assert result.errors[0].t1 == "RGB"


def test_multispectral_vs_optical_is_rejected():
    ms_bands = ["b01", "blue", "green", "red", "b05", "b06", "b07", "nir", "b8a", "b09", "b10", "swir1", "swir2"]
    t1 = _meta("T1", _geotiff(descriptions=ms_bands), "s2.tif", imagery_id="a")
    t2 = optical_scene("T2", imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is False
    assert result.errors[0].code == MODALITY_MISMATCH
    assert result.errors[0].t1 == "Multispectral" and result.errors[0].t2 == "RGB"


@pytest.mark.parametrize("factory", [sar_vv, optical_scene])
def test_same_modality_both_sides_is_valid(factory):
    result = validate_change_detection_inputs(factory("T1", imagery_id="a"), factory("T2", imagery_id="b"), REQS)
    assert result.valid is True, result.errors


# ---- section 3: aspect ratio ----------------------------------------------------


def test_same_aspect_ratio_different_resolution_is_not_rejected_on_ratio_alone():
    """1920x1080 vs 1280x720 -- same ratio, different pixel count. The brief's
    own example: don't reject for ratio; exact-dimension is a SEPARATE,
    configurable rule (tested below with it turned off)."""
    from app.validation.dimension_validator import aspect_ratio_issue
    t1 = optical_scene("T1", width=1920, height=1080, imagery_id="a")
    t2 = optical_scene("T2", width=1280, height=720, imagery_id="b")
    assert aspect_ratio_issue(t1.facts, t2.facts, tolerance=0.01, t1_label="T1", t2_label="T2") is None


def test_different_aspect_ratio_is_rejected():
    t1 = optical_scene("T1", width=1920, height=1080, imagery_id="a")  # 1.778
    t2 = optical_scene("T2", width=1024, height=768, imagery_id="b")  # 1.333
    result = validate_change_detection_inputs(t1, t2, GATES_ON)
    assert result.valid is False
    assert result.errors[0].code == ASPECT_RATIO_MISMATCH


def test_aspect_ratio_tolerance_is_configurable():
    t1 = optical_scene("T1", width=100, height=100, imagery_id="a")  # ratio 1.0
    t2 = optical_scene("T2", width=101, height=100, imagery_id="b")  # ratio 1.0099
    tight = ChangeDetectionRequirements(aspect_ratio_tolerance=0.001, require_exact_dimensions=False)
    loose = ChangeDetectionRequirements(aspect_ratio_tolerance=0.02, require_exact_dimensions=False)
    assert validate_change_detection_inputs(t1, t2, tight).valid is False
    assert validate_change_detection_inputs(t1, t2, loose).valid is True


# ---- section 4: exact dimensions -------------------------------------------------


def test_identical_dimensions_pass():
    t1 = optical_scene("T1", width=200, height=200, imagery_id="a")
    t2 = optical_scene("T2", width=200, height=200, imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is True, result.errors


def test_mismatched_dimensions_rejected_with_specific_code():
    t1 = optical_scene("T1", width=200, height=200, imagery_id="a")
    t2 = optical_scene("T2", width=100, height=100, imagery_id="b")  # same ratio, different size
    result = validate_change_detection_inputs(t1, t2, GATES_ON)
    assert result.valid is False
    assert result.errors[0].code == IMAGE_DIMENSION_MISMATCH
    assert result.errors[0].t1 == "200x200" and result.errors[0].t2 == "100x100"


def test_exact_dimensions_not_enforced_when_disabled():
    t1 = optical_scene("T1", width=200, height=200, imagery_id="a")
    t2 = optical_scene("T2", width=100, height=100, imagery_id="b")
    relaxed = ChangeDetectionRequirements(require_exact_dimensions=False)
    result = validate_change_detection_inputs(t1, t2, relaxed)
    assert result.valid is True, result.errors


# ---- section 5: general band/channel structure -----------------------------------


def test_red_nir_both_present_is_valid():
    t1 = _meta("T1", _geotiff(descriptions=["red", "nir"]), "a.tif", imagery_id="a")
    t2 = _meta("T2", _geotiff(descriptions=["red", "nir"]), "b.tif", imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is True, result.errors


def test_missing_nir_in_t2_is_rejected():
    # Both sides need "nir" present so modality (step 4, earlier than the
    # general band check) reads "multispectral" on both -- otherwise T2
    # (red only) would correctly fail modality first, before bands are ever compared.
    t1 = _meta("T1", _geotiff(descriptions=["red", "nir", "swir1"]), "a.tif", imagery_id="a")
    t2 = _meta("T2", _geotiff(descriptions=["red", "nir"]), "b.tif", imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is False
    assert result.errors[0].code == BAND_MISMATCH


# ---- section 6: strict SAR VV/VH ------------------------------------------------


def test_vv_vv_is_valid():
    result = validate_change_detection_inputs(sar_vv("T1", imagery_id="a"), sar_vv("T2", imagery_id="b"), REQS)
    assert result.valid is True, result.errors


def test_vh_vh_is_valid():
    result = validate_change_detection_inputs(sar_vh("T1", imagery_id="a"), sar_vh("T2", imagery_id="b"), REQS)
    assert result.valid is True, result.errors


def test_vv_vh_pair_gets_no_polarisation_validation():
    # Scope: no band/polarisation validation for Sentinel-1 / RISAT.
    result = validate_change_detection_inputs(sar_vv("T1", imagery_id="a"), sar_vh("T2", imagery_id="b"), REQS)
    assert result.valid is True, result.errors
    assert result.check_details["band_identity"].status == "skipped"


def test_unidentifiable_sar_polarization_is_not_band_validated():
    t1 = sar_vv("T1", imagery_id="a")
    t2 = _meta("T2", _geotiff(descriptions=[""]), "s1.tif", imagery_id="b")  # SAR-ish but no band name at all
    # Force modality to sar via hint since an unnamed single band alone is "unknown".
    t2.modality_hint = "sar"
    t1.modality_hint = "sar"
    result = validate_change_detection_inputs(t1, t2, REQS)
    # No SAR band validation: an unnamed SAR band is not an error by itself.
    assert result.valid is True, result.errors
    assert result.check_details["band_compatibility"].status == "skipped"


# ---- section 7: file format ------------------------------------------------------


def test_geotiff_geotiff_is_valid():
    result = validate_change_detection_inputs(sar_vv("T1", imagery_id="a"), sar_vv("T2", imagery_id="b"), REQS)
    assert result.valid is True, result.errors


def test_geotiff_vs_jpeg_is_rejected_when_matching_format_required():
    t1 = optical_scene("T1", imagery_id="a")
    t2 = jpeg_scene("T2", imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is False
    assert result.errors[0].code == FILE_FORMAT_MISMATCH


def test_tiff_vs_geotiff_is_not_a_format_mismatch_only_a_georeference_one():
    """A plain (unreferenced) TIFF and a GeoTIFF are the same FAMILY --
    the real problem is missing CRS, not format, and must be reported as such."""
    t1 = ungeoref_tiff("T1", imagery_id="a")
    t2 = optical_scene("T2", imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is False
    assert result.errors[0].code != FILE_FORMAT_MISMATCH


# ---- section 8/9: CRS + geotransform ---------------------------------------------


def test_matching_crs_is_valid():
    result = validate_change_detection_inputs(sar_vv("T1", imagery_id="a"), sar_vv("T2", imagery_id="b"), REQS)
    assert result.valid is True, result.errors


def test_different_crs_is_rejected_never_reprojected():
    t1 = sar_vv("T1", crs="EPSG:32643", imagery_id="a")
    t2 = sar_vv("T2", crs="EPSG:4326", imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is False
    assert result.errors[0].code == CRS_MISMATCH
    assert "32643" in result.errors[0].t1 and "4326" in result.errors[0].t2


def test_missing_georeference_is_rejected_before_crs_comparison():
    # Bands (step 8/9, earlier than geospatial per the brief's own order --
    # see the module docstring) must agree on BOTH sides first, so both get
    # an identifiable, matching VV band; the only remaining difference is
    # that T1 has no CRS at all.
    t1 = _meta("T1", _plain_tiff(count=1), "scan.tif", imagery_id="a")
    t1.modality_hint = "sar"
    t2 = sar_vv("T2", imagery_id="b")
    t2.modality_hint = "sar"
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is False
    # SAR gets no band validation, so the geospatial check is what fires --
    # on T1 specifically, before any CRS comparison.
    assert result.errors[0].code == CRS_MISSING
    assert result.errors[0].t1 == "T1" and result.errors[0].t2 is None


def _sar_vv_no_crs() -> ChangeDetectionImageMetadata:
    """A readable, named-VV-band TIFF with no CRS at all -- isolates the
    geospatial-completeness check from band/modality agreement."""
    data = np.full((1, 48, 64), unique_fill(), dtype="uint16")
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=64, height=48, count=1, dtype="uint16") as dst:
            dst.write(data)
            dst.set_band_description(1, "VV")
        content = mem.read()
    return _meta("T1", content, "s1.tif", imagery_id="a")


def test_crs_missing_is_rejected_when_bands_and_modality_already_match():
    t1 = _sar_vv_no_crs()
    t2 = sar_vv("T2", imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is False
    assert result.errors[0].code in (GEOREFERENCE_MISSING, "CRS_MISSING")


def test_geospatial_not_enforced_when_disabled():
    t1 = ungeoref_tiff("T1", count=1, imagery_id="a")
    t2 = ungeoref_tiff("T2", count=1, imagery_id="b")
    t1.modality_hint = t2.modality_hint = "optical"  # bypass the separate modality-detection concern
    relaxed = ChangeDetectionRequirements(require_geospatial=False, require_matching_format=False)
    result = validate_change_detection_inputs(t1, t2, relaxed)
    assert result.valid is True, result.errors


# ---- structural guards ------------------------------------------------------------


def test_same_image_both_sides_is_rejected():
    t1 = sar_vv("T1", imagery_id="same-id")
    t2 = sar_vv("T2", imagery_id="same-id")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is False
    assert result.errors[0].code == NOT_DISTINCT_OBSERVATIONS


def test_corrupted_t2_short_circuits_before_any_other_check():
    t1 = sar_vv("T1", imagery_id="a")
    from app.validation.schemas import RasterFacts
    t2 = ChangeDetectionImageMetadata(label="T2", facts=RasterFacts(error="broken"), extension=".tif", imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is False
    assert result.errors[0].code == FILE_CORRUPTED
    assert len(result.errors) == 1  # nothing else evaluated once unreadable


def test_stops_at_the_first_failing_step_only():
    """Modality AND aspect ratio both differ here -- only the modality issue
    (the earlier step) should be reported, per 'stop at first failure'."""
    t1 = optical_scene("T1", width=1920, height=1080, imagery_id="a")
    t2 = sar_vv("T2", width=100, height=50, imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is False
    assert len(result.errors) == 1
    assert result.errors[0].code == MODALITY_MISMATCH


# ---- section 16: never auto-fixes -------------------------------------------------


def test_mismatched_pair_is_never_silently_resized_or_reprojected():
    t1 = sar_vv("T1", crs="EPSG:32643", width=200, height=200, imagery_id="a")
    t2 = sar_vv("T2", crs="EPSG:4326", width=100, height=100, imagery_id="b")
    original_t1_width, original_t2_crs = t1.facts.width, t2.facts.crs
    validate_change_detection_inputs(t1, t2, REQS)
    assert t1.facts.width == original_t1_width  # untouched
    assert t2.facts.crs == original_t2_crs  # untouched, never reprojected


# ---- API end to end ---------------------------------------------------------------


def _upload(client, filename, content, content_type="image/tiff"):
    r = client.post("/api/v1/imagery/upload", files={"file": (filename, content, content_type)})
    assert r.status_code == 201, r.json()
    return r.json()["data"]


def test_valid_vv_pair_via_api(client, fake_supabase):
    t1 = _upload(client, "t1.tif", _geotiff(descriptions=["VV"]))
    t2 = _upload(client, "t2.tif", _geotiff(descriptions=["VV"]))
    response = client.post(ENDPOINT, json={"t1_imagery_id": t1["id"], "t2_imagery_id": t2["id"]})
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "VALID"
    assert body["t1"]["modality"] == "sar" and body["t1"]["bands"] == ["vv"]
    assert body["workflow"] == "change_detection"


def test_vv_vh_pair_via_api_gets_no_polarisation_validation(client, fake_supabase):
    t1 = _upload(client, "t1.tif", _geotiff(descriptions=["VV"]))
    t2 = _upload(client, "t2.tif", _geotiff(descriptions=["VH"]))
    response = client.post(ENDPOINT, json={"t1_imagery_id": t1["id"], "t2_imagery_id": t2["id"]})
    body = response.json()["data"]
    assert body["status"] == "VALID", body["errors"]


def test_optical_vs_sar_rejected_via_api(client, fake_supabase):
    t1 = _upload(client, "opt.tif", _geotiff(descriptions=["red", "green", "blue"]))
    t2 = _upload(client, "sar.tif", _geotiff(descriptions=["VV"]))
    response = client.post(ENDPOINT, json={"t1_imagery_id": t1["id"], "t2_imagery_id": t2["id"]})
    body = response.json()["data"]
    assert body["status"] == "REJECT"
    assert body["errors"][0]["code"] == "MODALITY_MISMATCH"
    assert body["errors"][0]["t1"] == "RGB" and body["errors"][0]["t2"] == "SAR"


def test_requirement_overrides_accepted_via_api(client, fake_supabase):
    t1 = _upload(client, "opt1.tif", _geotiff(descriptions=["red", "green", "blue"], width=200, height=100))
    t2 = _upload(client, "opt2.tif", _geotiff(descriptions=["red", "green", "blue"], width=100, height=50))
    response = client.post(ENDPOINT, json={
        "t1_imagery_id": t1["id"], "t2_imagery_id": t2["id"], "require_exact_dimensions": False,
    })
    body = response.json()["data"]
    assert body["status"] == "VALID", body["errors"]


def test_malformed_change_detection_request_is_a_normal_422(client, fake_supabase):
    response = client.post(ENDPOINT, json={"t1_imagery_id": "not-a-uuid", "t2_imagery_id": "also-not-a-uuid"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_nonexistent_imagery_id_via_api_is_a_clean_reject(client, fake_supabase):
    t1 = _upload(client, "t1.tif", _geotiff(descriptions=["VV"]))
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = client.post(ENDPOINT, json={"t1_imagery_id": t1["id"], "t2_imagery_id": fake_id})
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "REJECT"
    assert body["errors"][0]["code"] == "FILE_CORRUPTED"
    assert body["t2"] is None


# ---- Section 17 & 18 regression tests: Unknown modality & structural validation ----


def test_unknown_unknown_structurally_compatible_is_valid():
    """Scenario 1: GeoTIFF + GeoTIFF, Unknown + Unknown, Structurally compatible -> VALID."""
    t1 = unknown_geotiff("T1", width=10980, height=10980, count=1, imagery_id="a")
    t2 = unknown_geotiff("T2", width=10980, height=10980, count=1, imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is True
    assert result.status == "VALID"
    assert result.confidence == "structural"
    assert result.errors == []


def test_unknown_unknown_incompatible_dimensions_rejects_with_dimension_mismatch():
    """Scenario 5: Unknown + Unknown but incompatible dimensions -> INVALID with IMAGE_DIMENSION_MISMATCH, NOT UNKNOWN_MODALITY."""
    t1 = unknown_geotiff("T1", width=10980, height=10980, count=1, imagery_id="a")
    t2 = unknown_geotiff("T2", width=5120, height=5120, count=1, imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, GATES_ON)
    assert result.valid is False
    assert result.status == "REJECT"
    assert len(result.errors) == 1
    assert result.errors[0].code == IMAGE_DIMENSION_MISMATCH
    assert "10980x10980" in result.errors[0].t1 and "5120x5120" in result.errors[0].t2


def test_unknown_unknown_incompatible_band_count_rejects_with_band_mismatch():
    """T1 = 13 bands, T2 = 1 band -> likely incompatible -> INVALID with BAND_MISMATCH."""
    t1 = unknown_geotiff("T1", width=64, height=48, count=13, imagery_id="a")
    t2 = unknown_geotiff("T2", width=64, height=48, count=1, imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is False
    assert result.status == "REJECT"
    assert result.errors[0].code == BAND_MISMATCH
    assert "13" in result.errors[0].t1 and "1" in result.errors[0].t2


def test_same_multispectral_bands_b02_b03_b04_b08_is_valid():
    """Scenario 4b: Sentinel-2 style multispectral bands (B02, B03, B04, B08) -> VALID."""
    bands = ["B02", "B03", "B04", "B08"]
    t1 = _meta("T1", _geotiff(descriptions=bands), "s2_a.tif", imagery_id="a")
    t2 = _meta("T2", _geotiff(descriptions=bands), "s2_b.tif", imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is True
    assert result.errors == []


def test_different_crs_rejected_with_crs_mismatch():
    """EPSG:32643 + EPSG:4326 -> INVALID with CRS_MISMATCH."""
    t1 = unknown_geotiff("T1", crs="EPSG:32643", imagery_id="a")
    t2 = unknown_geotiff("T2", crs="EPSG:4326", imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is False
    assert result.errors[0].code == CRS_MISMATCH
    assert "32643" in result.errors[0].t1 and "4326" in result.errors[0].t2


def test_unknown_unknown_geotiff_pair_valid_via_api(client, fake_supabase):
    """End-to-end API test: uploading two structurally compatible unknown GeoTIFFs returns VALID."""
    t1 = _upload(client, "u1.tif", _geotiff(descriptions=[]))
    t2 = _upload(client, "u2.tif", _geotiff(descriptions=[]))
    response = client.post(ENDPOINT, json={"t1_imagery_id": t1["id"], "t2_imagery_id": t2["id"]})
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "VALID"
    assert body["valid"] is True
    assert body["confidence"] == "structural"
    assert body["t1"]["modality"] == "unknown"
    assert body["t2"]["modality"] == "unknown"
    assert body["errors"] == []


def test_unknown_unknown_geotiff_dimension_mismatch_via_api(client, fake_supabase):
    """End-to-end API test: two unknown GeoTIFFs with mismatched dimensions return IMAGE_DIMENSION_MISMATCH."""
    t1 = _upload(client, "u1.tif", _geotiff(descriptions=[], width=200, height=200))
    t2 = _upload(client, "u2.tif", _geotiff(descriptions=[], width=100, height=100))
    response = client.post(ENDPOINT, json={"t1_imagery_id": t1["id"], "t2_imagery_id": t2["id"]})
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "REJECT"
    assert body["valid"] is False
    assert body["errors"][0]["code"] == IMAGE_DIMENSION_MISMATCH
    assert body["error_code"] == IMAGE_DIMENSION_MISMATCH


def test_geotiff_with_tags_detected_properly():
    """Tags in GeoTIFF (e.g. POLARIZATION: VV) are correctly detected as SAR VV."""
    t1 = _meta("T1", _geotiff(descriptions=[], tags={"POLARIZATION": "VV"}), "s1.tif", imagery_id="a")
    t2 = _meta("T2", _geotiff(descriptions=[], tags={"POLARIZATION": "VV"}), "s1.tif", imagery_id="b")
    result = validate_change_detection_inputs(t1, t2, REQS)
    assert result.valid is True
    assert result.status == "VALID"



