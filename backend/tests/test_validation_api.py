"""POST /api/v1/validation/validate end to end: imagery_id -> Storage -> verdict
(task brief sections 13, 14). `client`/`fake_supabase` come from conftest.py --
the SAME fake Supabase + Storage every other route's tests use.
"""
import numpy as np
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.services import imagery_service, storage_service

ENDPOINT = "/api/v1/validation/validate"


def _geotiff(*, count=13, descriptions=None, crs="EPSG:32643"):
    data = np.zeros((count, 48, 64), dtype="uint16")
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=64, height=48, count=count, dtype="uint16", crs=crs, transform=from_origin(776000, 1440000, 10, 10)) as dst:
            dst.write(data)
            for i, name in enumerate(descriptions or [], start=1):
                dst.set_band_description(i, name)
        return mem.read()


def _jpeg():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def _upload_tiff(client, filename="s2.tif", **kwargs):
    r = client.post("/api/v1/imagery/upload", files={"file": (filename, _geotiff(**kwargs), "image/tiff")})
    assert r.status_code == 201, r.json()
    return r.json()["data"]


def _upload_jpeg(client, filename="photo.jpg"):
    r = client.post("/api/v1/imagery/upload", files={"file": (filename, _jpeg(), "image/jpeg")})
    assert r.status_code == 201, r.json()
    return r.json()["data"]


def test_valid_ndvi_request_against_a_real_uploaded_scene(client, fake_supabase):
    band_names = ["b01", "blue", "green", "red", "b05", "b06", "b07", "nir", "b8a", "b09", "b10", "swir1", "swir2"]
    uploaded = _upload_tiff(client, descriptions=band_names)

    response = client.post(ENDPOINT, json={"workflow": "ndvi", "images": [{"imagery_id": uploaded["id"]}]})
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "VALID"
    assert body["valid"] is True
    assert body["inputs"][0]["modality"] == "multispectral"
    assert set(body["inputs"][0]["detected_bands"]) >= {"red", "nir"}


def test_rgb_jpeg_rejected_for_ndvi_via_api(client, fake_supabase):
    uploaded = _upload_jpeg(client)
    response = client.post(ENDPOINT, json={"workflow": "ndvi", "images": [{"imagery_id": uploaded["id"]}]})
    body = response.json()["data"]
    assert body["status"] == "REJECT"
    assert any(e["code"] == "BAND_MISSING" for e in body["errors"])


def test_nonexistent_imagery_id_is_image_unavailable_not_a_500(client, fake_supabase):
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = client.post(ENDPOINT, json={"workflow": "visual_vqa", "images": [{"imagery_id": fake_id}]})
    assert response.status_code == 200  # this endpoint doesn't fail the REQUEST for a bad reference
    body = response.json()["data"]
    assert body["status"] == "REJECT"
    assert body["errors"][0]["code"] == "IMAGE_UNAVAILABLE"


def test_unknown_workflow_via_api(client, fake_supabase):
    uploaded = _upload_jpeg(client)
    response = client.post(ENDPOINT, json={"workflow": "nonsense", "images": [{"imagery_id": uploaded["id"]}]})
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "REJECT"
    assert body["errors"][0]["code"] == "UNKNOWN_WORKFLOW"


def test_malformed_request_body_is_a_normal_422(client, fake_supabase):
    response = client.post(ENDPOINT, json={"workflow": "ndvi", "images": []})  # min_length=1 violated
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_two_image_bitemporal_request_via_api(client, fake_supabase):
    t1 = _upload_tiff(client, filename="t1.tif", count=1, descriptions=["VV"])
    t2 = _upload_tiff(client, filename="t2.tif", count=1, descriptions=["VV"])

    response = client.post(ENDPOINT, json={
        "workflow": "sar_change_vv",
        "images": [{"imagery_id": t1["id"], "role": "t1"}, {"imagery_id": t2["id"], "role": "t2"}],
    })
    body = response.json()["data"]
    assert body["status"] == "VALID", body["errors"]


def test_aoi_outside_a_real_uploaded_scenes_bounds_via_api(client, fake_supabase):
    uploaded = _upload_tiff(client, descriptions=["red", "green", "blue"] + ["b"] * 10)
    aoi = {"type": "Polygon", "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]]}
    response = client.post(ENDPOINT, json={"workflow": "visual_vqa", "images": [{"imagery_id": uploaded["id"]}], "aoi": aoi})
    body = response.json()["data"]
    assert body["status"] == "REJECT"
    assert body["errors"][0]["code"] == "AOI_OUTSIDE_IMAGE"


def test_known_properties_path_never_re_downloads_the_original(client, fake_supabase, monkeypatch):
    """A TIFF already carries its structure in imagery.metadata.raster.properties
    (written at upload time) -- build_validation_image must use that directly,
    never re-download the original file, for exactly the reason section 14
    gives ("don't duplicate the uploaded binary unnecessarily")."""
    uploaded = _upload_tiff(client, descriptions=["red", "green", "blue"] + ["b"] * 10)

    def _fail(*a, **k):
        raise AssertionError("download_file should not be called when metadata.raster.properties already exists")
    monkeypatch.setattr(storage_service, "download_file", _fail)

    image = imagery_service.build_validation_image(uploaded["id"])
    assert image.known_properties is not None
    assert image.content is None


def test_jpeg_without_stored_properties_does_download(client, fake_supabase):
    """JPEG/PNG never get metadata.raster.properties (only TIFFs do, via
    raster_service) -- build_validation_image must fall back to a real
    download so the structure can still be inspected."""
    uploaded = _upload_jpeg(client)
    image = imagery_service.build_validation_image(uploaded["id"])
    assert image.known_properties is None
    assert image.content is not None and len(image.content) > 0
