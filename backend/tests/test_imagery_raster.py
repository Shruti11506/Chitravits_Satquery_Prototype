"""TIFF/GeoTIFF uploads: generated thumbnail + real georeference (raster_service)."""
import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.services import raster_service
from tests.images import real_png

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _geotiff(*, count=3, dtype="uint16", crs="EPSG:32643", width=64, height=48, nodata=None, tags=None, descriptions=None, seed=0):
    """A small real GeoTIFF: UTM 43N, 10 m pixels, top-left at (776000, 1440000) -- near Bengaluru."""
    rng = np.random.default_rng(seed)
    data = rng.integers(100, 4000, size=(count, height, width)).astype(dtype)
    if nodata is not None:
        data[:, :4, :] = nodata
    with MemoryFile() as mem:
        with mem.open(
            driver="GTiff", width=width, height=height, count=count, dtype=dtype,
            crs=crs, transform=from_origin(776000, 1440000, 10, 10), nodata=nodata,
        ) as dst:
            dst.write(data)
            if tags:
                dst.update_tags(**tags)
            for i, name in enumerate(descriptions or [], start=1):
                dst.set_band_description(i, name)
        return mem.read()


def _upload(client, filename, content, content_type="image/tiff"):
    return client.post("/api/v1/imagery/upload", files={"file": (filename, content, content_type)})


def test_geotiff_upload_stores_thumbnail_and_real_coordinates(client, fake_supabase):
    response = _upload(client, "scene.tif", _geotiff())
    assert response.status_code == 201
    data = response.json()["data"]

    thumb_key = f"Satquery/{data['storage_path'].rsplit('/', 1)[0]}/thumbnail.png"
    assert fake_supabase.storage.objects[thumb_key].startswith(PNG_SIGNATURE)
    assert "/sign/" in data["thumbnail_url"]

    # Centre of the raster, reprojected from UTM 43N: ~13.02 N, 77.55 E.
    assert data["latitude"] == pytest.approx(13.02, abs=0.01)
    assert data["longitude"] == pytest.approx(77.547, abs=0.005)
    assert data["bbox"]["crs"] == "EPSG:4326"
    assert data["bbox"]["source_crs"] == "EPSG:32643"
    assert data["bbox"]["west"] < data["longitude"] < data["bbox"]["east"]
    assert data["bbox"]["south"] < data["latitude"] < data["bbox"]["north"]
    assert data["cloud_cover"] is None  # the file carries no cloud-cover tag

    row = fake_supabase.store["imagery"][0]
    assert row["latitude"] == data["latitude"] and row["bbox"] == data["bbox"]
    assert "cloud_cover" not in row  # never written when absent


def test_get_imagery_returns_thumbnail_url_and_coordinates(client):
    uploaded = _upload(client, "scene.tiff", _geotiff()).json()["data"]
    data = client.get(f"/api/v1/imagery/{uploaded['id']}").json()["data"]
    assert data["url"] and "/sign/" in data["url"]
    assert data["thumbnail_url"].split("?")[0].endswith("/thumbnail.png")
    assert data["latitude"] == uploaded["latitude"]
    assert data["bbox"] == uploaded["bbox"]


def test_conversation_detail_includes_thumbnail_url(client):
    conversation = client.post("/api/v1/conversations").json()["data"]
    client.post(
        "/api/v1/imagery/upload",
        files={"file": ("scene.tif", _geotiff(), "image/tiff")},
        data={"conversation_id": conversation["id"]},
    )
    detail = client.get(f"/api/v1/conversations/{conversation['id']}").json()["data"]
    assert detail["imagery"][0]["thumbnail_url"]


def test_cloud_cover_only_from_a_real_tag(client):
    data = _upload(client, "s2.tif", _geotiff(tags={"CLOUDY_PIXEL_PERCENTAGE": "12.5"})).json()["data"]
    assert data["cloud_cover"] == 12.5


def test_corrupt_tiff_is_rejected_before_anything_is_stored(client, fake_supabase):
    response = _upload(client, "broken.tif", b"II*\x00 not really a tiff")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FILE_CORRUPTED"
    assert fake_supabase.storage.objects == {}


def test_tiff_without_crs_gets_thumbnail_but_no_coordinates(client):
    data = _upload(client, "plain.tif", _geotiff(crs=None)).json()["data"]
    assert data["thumbnail_url"]
    assert data["latitude"] is None and data["bbox"] is None


def test_thumbnail_upload_failure_keeps_the_upload(client, fake_supabase, monkeypatch):
    from app.services import storage_service

    real_upload = storage_service.upload_file

    def fail_previews(client_, path, content, content_type, upsert=False):
        if path.endswith("/thumbnail.png"):
            raise storage_service.StorageError("simulated")
        return real_upload(client_, path, content, content_type, upsert)

    monkeypatch.setattr(storage_service, "upload_file", fail_previews)
    response = _upload(client, "scene.tif", _geotiff())
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["thumbnail_url"] is None
    assert data["preview_status"] == "failed" and data["preview_path"] is None
    assert data["raster"]["preview_error"] == "The preview was generated but could not be stored."
    assert data["latitude"] is not None  # coordinates come from the file, not the thumbnail
    assert list(fake_supabase.storage.objects) == [f"Satquery/{data['storage_path']}"]  # original kept


def test_png_upload_is_unaffected(client, fake_supabase, monkeypatch):
    called = []
    monkeypatch.setattr(raster_service, "extract", lambda content: called.append(1))
    response = _upload(client, "photo.png", real_png(), "image/png")
    assert response.status_code == 201
    data = response.json()["data"]
    assert called == []
    assert data["thumbnail_url"] is None and data["latitude"] is None
    assert len(fake_supabase.storage.objects) == 1
    assert client.get(f"/api/v1/imagery/{data['id']}").json()["data"]["thumbnail_url"] is None


def test_delete_removes_thumbnail_too(client, fake_supabase):
    data = _upload(client, "scene.tif", _geotiff()).json()["data"]
    assert len(fake_supabase.storage.objects) == 2
    assert client.delete(f"/api/v1/imagery/{data['id']}").status_code == 200
    assert fake_supabase.storage.objects == {}


def test_thumbnail_is_downscaled_and_masks_nodata():
    info = raster_service.extract(_geotiff(width=3000, height=1500, nodata=0))
    with MemoryFile(info.thumbnail_png) as mem, mem.open() as png:
        assert max(png.width, png.height) == raster_service.THUMBNAIL_MAX_EDGE
        assert png.count == 4  # RGB + alpha, because the file has nodata pixels
        alpha = png.read(4)
        assert alpha[0].max() == 0 and alpha[-1].min() == 255


def test_named_sentinel2_bands_render_as_true_colour():
    content = _geotiff(count=4, descriptions=["B2", "B3", "B4", "B8"])
    with MemoryFile(content) as mem, mem.open() as src:
        assert raster_service._pick_bands(src) == ([3, 2, 1], "true_color")


def test_single_band_renders_grayscale():
    info = raster_service.extract(_geotiff(count=1, dtype="float32"))
    with MemoryFile(info.thumbnail_png) as mem, mem.open() as png:
        assert png.count == 1
