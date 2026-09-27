"""Regression tests for the reported bug: the backend queued an analysis
request for an incompatible T1/T2 pair (a plain RGB JPEG against a
Sentinel-2 multispectral GeoTIFF) instead of rejecting it.

These exercise the REAL end-to-end path -- upload via the actual endpoints,
then POST /api/v1/analysis -- not the validator functions directly (see
test_change_detection_validation.py for that), because the bug was in the
WIRING (`analysis_service.create_analysis` never called the validator at
all), not in the validation logic itself.
"""
import io

import numpy as np
from PIL import Image
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

ANALYSIS_ENDPOINT = "/api/v1/analysis"
S2_BAND_NAMES = ["b01", "blue", "green", "red", "b05", "b06", "b07", "nir", "b8a", "b09", "b10", "swir1", "swir2"]


def _geotiff(*, descriptions, crs="EPSG:32643", width=64, height=48, count=None):
    count = count if count is not None else len(descriptions)
    data = np.zeros((count, height, width), dtype="uint16")
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=width, height=height, count=count, dtype="uint16", crs=crs, transform=from_origin(776000, 1440000, 10, 10)) as dst:
            dst.write(data)
            for i, name in enumerate(descriptions, start=1):
                dst.set_band_description(i, name)
        return mem.read()


def _plain_tiff(*, width=64, height=48, count=1):
    data = np.zeros((count, height, width), dtype="uint8")
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=width, height=height, count=count, dtype="uint8") as dst:
            dst.write(data)
        return mem.read()


def _jpeg(width=64, height=48):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def _upload(client, filename, content, content_type):
    response = client.post("/api/v1/imagery/upload", files={"file": (filename, content, content_type)})
    assert response.status_code == 201, response.json()
    return response.json()["data"]["id"]


def _submit(client, t1_id, t2_id, *, query="Compare these two images."):
    return client.post(ANALYSIS_ENDPOINT, json={
        "imagery_id": t1_id, "comparison_imagery_id": t2_id, "analysis_type": "general_analysis", "query": query,
    })


def _assert_rejected(client, fake_supabase, t1_id, t2_id, *, expected_codes):
    before = len(fake_supabase.store.get("analysis_jobs", []))
    response = _submit(client, t1_id, t2_id)
    assert response.status_code == 422, response.json()
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] in expected_codes, body["error"]
    # The core acceptance criterion: nothing was queued.
    assert len(fake_supabase.store.get("analysis_jobs", [])) == before
    return body["error"]


def _assert_valid(client, fake_supabase, t1_id, t2_id):
    response = _submit(client, t1_id, t2_id)
    assert response.status_code == 201, response.json()
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert data["imagery_id"] == t1_id and data["comparison_imagery_id"] == t2_id
    return data


# ---- THE reported bug, exactly as described ------------------------------------


def test_the_exact_reported_bug_is_now_rejected(client, fake_supabase):
    """T1 = images.jpeg (RGB/Optical), T2 = S2A_MSI2LA_....tif (Sentinel-2
    multispectral). Previously: queued. Now: rejected, nothing queued,
    nothing runs downstream."""
    t1 = _upload(client, "images.jpeg", _jpeg(), "image/jpeg")
    t2 = _upload(client, "S2A_MSI2LA_20260101T000000_dummy.tif", _geotiff(descriptions=S2_BAND_NAMES), "image/tiff")

    error = _assert_rejected(client, fake_supabase, t1, t2, expected_codes={"MODALITY_MISMATCH", "IMAGE_TYPE_MISMATCH"})

    # The rich diagnostic payload the frontend renders (section 13/14).
    assert error["details"]["workflow"] == "change_detection"
    assert error["details"]["t1"]["filename"] == "images.jpeg"
    assert error["details"]["t1"]["format"] == "JPEG"
    assert error["details"]["t1"]["modality"] == "rgb"
    assert error["details"]["t2"]["format"] == "GeoTIFF"
    assert error["details"]["t2"]["modality"] == "multispectral"
    assert len(error["details"]["errors"]) >= 1


# ---- section 17's full scenario list, via the real endpoint --------------------


def test_jpeg_plus_jpeg_is_valid(client, fake_supabase):
    t1 = _upload(client, "a.jpg", _jpeg(), "image/jpeg")
    t2 = _upload(client, "b.jpg", _jpeg(), "image/jpeg")
    _assert_valid(client, fake_supabase, t1, t2)


def test_geotiff_plus_geotiff_is_valid(client, fake_supabase):
    content = _geotiff(descriptions=["red", "green", "blue"])
    t1 = _upload(client, "t1.tif", content, "image/tiff")
    t2 = _upload(client, "t2.tif", content, "image/tiff")
    _assert_valid(client, fake_supabase, t1, t2)


def test_sar_vv_plus_vv_is_valid(client, fake_supabase):
    t1 = _upload(client, "t1.tif", _geotiff(descriptions=["VV"]), "image/tiff")
    t2 = _upload(client, "t2.tif", _geotiff(descriptions=["VV"]), "image/tiff")
    _assert_valid(client, fake_supabase, t1, t2)


def test_sar_vh_plus_vh_is_valid(client, fake_supabase):
    t1 = _upload(client, "t1.tif", _geotiff(descriptions=["VH"]), "image/tiff")
    t2 = _upload(client, "t2.tif", _geotiff(descriptions=["VH"]), "image/tiff")
    _assert_valid(client, fake_supabase, t1, t2)


def test_sar_vv_plus_vh_is_rejected(client, fake_supabase):
    t1 = _upload(client, "t1.tif", _geotiff(descriptions=["VV"]), "image/tiff")
    t2 = _upload(client, "t2.tif", _geotiff(descriptions=["VH"]), "image/tiff")
    _assert_rejected(client, fake_supabase, t1, t2, expected_codes={"BAND_MISMATCH"})


def test_optical_plus_sar_is_rejected(client, fake_supabase):
    t1 = _upload(client, "opt.tif", _geotiff(descriptions=["red", "green", "blue"]), "image/tiff")
    t2 = _upload(client, "sar.tif", _geotiff(descriptions=["VV"]), "image/tiff")
    _assert_rejected(client, fake_supabase, t1, t2, expected_codes={"MODALITY_MISMATCH", "IMAGE_TYPE_MISMATCH"})


def test_rgb_plus_multispectral_is_rejected(client, fake_supabase):
    t1 = _upload(client, "rgb.tif", _geotiff(descriptions=["red", "green", "blue"]), "image/tiff")
    t2 = _upload(client, "s2.tif", _geotiff(descriptions=S2_BAND_NAMES), "image/tiff")
    _assert_rejected(client, fake_supabase, t1, t2, expected_codes={"MODALITY_MISMATCH", "IMAGE_TYPE_MISMATCH"})


def test_different_dimensions_is_rejected(client, fake_supabase):
    t1 = _upload(client, "t1.tif", _geotiff(descriptions=["red", "green", "blue"], width=200, height=200), "image/tiff")
    t2 = _upload(client, "t2.tif", _geotiff(descriptions=["red", "green", "blue"], width=100, height=100), "image/tiff")
    _assert_rejected(client, fake_supabase, t1, t2, expected_codes={"IMAGE_DIMENSION_MISMATCH"})


def test_different_aspect_ratios_is_rejected(client, fake_supabase):
    t1 = _upload(client, "t1.tif", _geotiff(descriptions=["red", "green", "blue"], width=1920, height=1080), "image/tiff")
    t2 = _upload(client, "t2.tif", _geotiff(descriptions=["red", "green", "blue"], width=1024, height=768), "image/tiff")
    _assert_rejected(client, fake_supabase, t1, t2, expected_codes={"ASPECT_RATIO_MISMATCH"})


def test_different_crs_is_rejected(client, fake_supabase):
    t1 = _upload(client, "t1.tif", _geotiff(descriptions=["red", "green", "blue"], crs="EPSG:32643"), "image/tiff")
    t2 = _upload(client, "t2.tif", _geotiff(descriptions=["red", "green", "blue"], crs="EPSG:4326"), "image/tiff")
    _assert_rejected(client, fake_supabase, t1, t2, expected_codes={"CRS_MISMATCH"})


def test_missing_crs_is_rejected(client, fake_supabase):
    t1 = _upload(client, "t1.tif", _plain_tiff(), "image/tiff")
    t2 = _upload(client, "t2.tif", _geotiff(descriptions=["red", "green", "blue"]), "image/tiff")
    # T1 has no named bands either, so modality (checked first) is what
    # actually fires here -- both "missing CRS" and "unidentified modality"
    # are honest reasons for the SAME under-described file to be rejected;
    # either is an acceptable, non-fabricated answer.
    _assert_rejected(client, fake_supabase, t1, t2, expected_codes={
        "MODALITY_MISMATCH", "IMAGE_TYPE_MISMATCH", "UNKNOWN_MODALITY", "CRS_MISSING", "GEOREFERENCE_MISSING",
    })


def test_missing_crs_is_rejected_when_modality_is_otherwise_unambiguous(client, fake_supabase):
    """Isolates the CRS-missing rule from modality ambiguity: both sides
    carry named RGB bands (so modality agrees), only T1 lacks a CRS."""
    data = np.zeros((3, 48, 64), dtype="uint16")
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=64, height=48, count=3, dtype="uint16") as dst:
            dst.write(data)
            for i, name in enumerate(["red", "green", "blue"], start=1):
                dst.set_band_description(i, name)
        t1_content = mem.read()

    t1 = _upload(client, "t1.tif", t1_content, "image/tiff")
    t2 = _upload(client, "t2.tif", _geotiff(descriptions=["red", "green", "blue"]), "image/tiff")
    _assert_rejected(client, fake_supabase, t1, t2, expected_codes={"CRS_MISSING", "GEOREFERENCE_MISSING"})


def test_reproduce_screenshot_multispectral_geotiff_t1_and_rgb_jpeg_t2(client, fake_supabase):
    """Reproducing Section 20 test:
    T1 = Sentinel-2 multispectral GeoTIFF
    T2 = RGB JPEG
    workflow = change_detection
    Expected: result.valid is False, code is IMAGE_TYPE_MISMATCH, no jobs queued.
    """
    before_jobs = len(fake_supabase.store.get("analysis_jobs", []))
    t1 = _upload(client, "S2A_MSI2LA_20260101T000000_dummy.tif", _geotiff(descriptions=S2_BAND_NAMES), "image/tiff")
    t2 = _upload(client, "images.jpeg", _jpeg(), "image/jpeg")

    # 1. Test via validation endpoint
    val_resp = client.post("/api/v1/validation/change-detection", json={
        "t1_imagery_id": t1,
        "t2_imagery_id": t2,
    })
    assert val_resp.status_code == 200
    val_body = val_resp.json()["data"]
    assert val_body["valid"] is False
    assert val_body["status"] == "REJECT"
    assert val_body["errors"][0]["code"] == "IMAGE_TYPE_MISMATCH"

    # 2. Test via analysis creation endpoint -- hard gate rejection
    err = _assert_rejected(client, fake_supabase, t1, t2, expected_codes={"IMAGE_TYPE_MISMATCH", "MODALITY_MISMATCH"})
    assert err["code"] == "IMAGE_TYPE_MISMATCH"
    assert err["details"]["valid"] is False
    assert err["details"]["status"] == "REJECTED"
    assert err["details"]["workflow"] == "change_detection"
    assert err["details"]["error_code"] == "IMAGE_TYPE_MISMATCH"
    assert err["details"]["t1"]["modality"] == "multispectral"
    assert err["details"]["t2"]["modality"] == "rgb"

    # Assert no job was created or queued
    after_jobs = len(fake_supabase.store.get("analysis_jobs", []))
    assert after_jobs == before_jobs


def test_unknown_modality_is_rejected_with_code(client, fake_supabase):
    """T1 has unknown modality (plain unbanded tiff without sensor), T2 has optical bands."""
    t1 = _upload(client, "unknown.tif", _plain_tiff(), "image/tiff")
    t2 = _upload(client, "optical.tif", _geotiff(descriptions=["red", "green", "blue"]), "image/tiff")

    val_resp = client.post("/api/v1/validation/change-detection", json={
        "t1_imagery_id": t1,
        "t2_imagery_id": t2,
    })
    assert val_resp.status_code == 200
    val_body = val_resp.json()["data"]
    assert val_body["valid"] is False
    assert val_body["errors"][0]["code"] == "UNKNOWN_MODALITY"

    _assert_rejected(client, fake_supabase, t1, t2, expected_codes={"UNKNOWN_MODALITY"})