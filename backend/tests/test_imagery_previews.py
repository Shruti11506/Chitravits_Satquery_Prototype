"""TIFF previews are recorded on the row (migration 0007) and filled in once for older rows."""
import uuid

import numpy as np
from rasterio.enums import ColorInterp
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.services import raster_service
from tests.fakes import FakeApiError
from tests.test_imagery_raster import _geotiff
from tests.images import real_png

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _upload(client, filename, content, content_type="image/tiff", **form):
    return client.post("/api/v1/imagery/upload", files={"file": (filename, content, content_type)}, data=form)


def _legacy_row(fake_supabase, content, *, preview_status_column=True, with_thumbnail=None, conversation_id=None):
    """An imagery row stored the old way: original in Storage, no preview recorded."""
    folder = f"imagery/{uuid.uuid4()}"
    path = f"{folder}/old_scene.tif"
    fake_supabase.storage.objects[f"Satquery/{path}"] = content
    if with_thumbnail is not None:
        fake_supabase.storage.objects[f"Satquery/{folder}/thumbnail.png"] = with_thumbnail
    row = {
        "id": str(uuid.uuid4()),
        "name": "old_scene.tif",
        "original_filename": "old_scene.tif",
        "bucket": "Satquery",
        "storage_path": path,
        "mime_type": "image/tiff",
        "file_size": len(content),
        "metadata": None,
        "latitude": None,
        "longitude": None,
        "bbox": None,
        "cloud_cover": None,
        "conversation_id": conversation_id,
        "created_at": "2026-09-25T17:49:00+00:00",
    }
    if preview_status_column:  # migration 0007 applied: the columns exist, still NULL
        row.update({"preview_path": None, "preview_status": None})
    fake_supabase.store.setdefault("imagery", []).append(row)
    return row


def _count_extract_calls(monkeypatch):
    calls = []
    real_extract = raster_service.extract

    def counting(content):
        calls.append(1)
        return real_extract(content)

    monkeypatch.setattr(raster_service, "extract", counting)
    return calls


def test_upload_records_the_preview_and_keeps_the_original(client, fake_supabase):
    original = _geotiff()
    data = _upload(client, "scene.tif", original).json()["data"]

    folder = data["storage_path"].rsplit("/", 1)[0]
    assert data["preview_status"] == "ready"
    assert data["preview_path"] == f"{folder}/thumbnail.png"
    assert fake_supabase.storage.objects[f"Satquery/{data['storage_path']}"] == original  # untouched
    assert fake_supabase.storage.objects[f"Satquery/{data['preview_path']}"].startswith(PNG_SIGNATURE)
    assert data["preview_path"] in data["thumbnail_url"]

    row = fake_supabase.store["imagery"][0]
    assert row["preview_path"] == data["preview_path"] and row["preview_status"] == "ready"
    props = row["metadata"]["raster"]["properties"]
    assert (props["width"], props["height"], props["band_count"]) == (64, 48, 3)
    assert props["dtypes"] == ["uint16"] * 3 and props["crs"] == "EPSG:32643" and props["georeferenced"] is True
    assert props["transform"][:3] == [10.0, 0.0, 776000.0]
    assert row["metadata"]["raster"]["preview"]["mode"] == "band_composite"  # unnamed bands: not true colour
    assert data["raster"]["properties"]["band_count"] == 3


def test_user_metadata_is_kept_next_to_raster_facts(client, fake_supabase):
    _upload(client, "scene.tif", _geotiff(), metadata='{"note": "field trip"}')
    metadata = fake_supabase.store["imagery"][0]["metadata"]
    assert metadata["note"] == "field trip" and "raster" in metadata


def test_unreadable_tiff_is_rejected_at_upload_and_nothing_is_stored(client, fake_supabase):
    # Upload now runs full file validation: a TIFF whose header can't be
    # parsed is FILE_CORRUPTED (it used to be stored with preview "failed").
    response = _upload(client, "broken.tif", b"II*\x00 not really a tiff")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FILE_CORRUPTED"
    assert fake_supabase.storage.objects == {}
    assert fake_supabase.store.get("imagery", []) == []


def test_png_rows_get_no_preview_fields(client, fake_supabase):
    data = _upload(client, "photo.png", real_png(), "image/png").json()["data"]
    assert data["preview_status"] is None and data["preview_path"] is None and data["raster"] is None
    assert "preview_status" not in fake_supabase.store["imagery"][0]


def test_multispectral_and_rgba_previews_render(client):
    multispectral = _upload(client, "ms.tif", _geotiff(count=13)).json()["data"]
    assert multispectral["preview_status"] == "ready"
    assert multispectral["raster"]["preview"]["mode"] == "band_composite"

    rng = np.random.default_rng(3)
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=40, height=30, count=4, dtype="uint8", crs="EPSG:4326",
                      transform=from_origin(77.5, 13.0, 0.001, 0.001)) as dst:
            dst.write(rng.integers(0, 255, size=(4, 30, 40)).astype("uint8"))
            dst.colorinterp = [ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha]
        rgba = mem.read()
    data = _upload(client, "rgba.tif", rgba).json()["data"]
    assert data["preview_status"] == "ready" and data["raster"]["preview"]["mode"] == "true_color"


def test_insert_failure_removes_the_original_and_the_preview(client, fake_supabase, monkeypatch):
    real_table = fake_supabase.table

    class FailingInsert:
        def insert(self, row):
            return self

        def execute(self):
            raise FakeApiError("Could not find the 'preview_path' column of 'imagery'", "PGRST204")

    monkeypatch.setattr(fake_supabase, "table", lambda name: FailingInsert() if name == "imagery" else real_table(name))
    response = _upload(client, "scene.tif", _geotiff())
    assert response.status_code == 503
    assert "0007_imagery_previews.sql" in response.json()["error"]["message"]
    assert fake_supabase.storage.objects == {}


def test_older_tiff_gets_its_preview_once(client, fake_supabase, monkeypatch):
    row = _legacy_row(fake_supabase, _geotiff())
    calls = _count_extract_calls(monkeypatch)

    first = client.get(f"/api/v1/imagery/{row['id']}").json()["data"]
    assert first["preview_status"] == "ready" and first["thumbnail_url"]
    assert first["latitude"] is not None and first["bbox"]["crs"] == "EPSG:4326"  # georeference filled too
    assert fake_supabase.storage.objects[f"Satquery/{first['preview_path']}"].startswith(PNG_SIGNATURE)
    stored = fake_supabase.store["imagery"][0]
    assert stored["preview_status"] == "ready" and stored["metadata"]["raster"]["properties"]["band_count"] == 3

    second = client.get(f"/api/v1/imagery/{row['id']}").json()["data"]
    assert second["thumbnail_url"] and calls == [1]  # cached: not regenerated


def test_older_tiff_with_an_existing_thumbnail_is_just_recorded(client, fake_supabase, monkeypatch):
    row = _legacy_row(fake_supabase, _geotiff(), with_thumbnail=PNG_SIGNATURE + b"old preview")
    calls = _count_extract_calls(monkeypatch)
    data = client.get(f"/api/v1/imagery/{row['id']}").json()["data"]
    assert data["preview_status"] == "ready" and data["preview_path"].endswith("/thumbnail.png")
    assert calls == []


def test_older_unreadable_tiff_is_recorded_as_failed_once(client, fake_supabase, monkeypatch):
    row = _legacy_row(fake_supabase, b"II*\x00 junk")
    calls = _count_extract_calls(monkeypatch)
    for _ in range(2):
        data = client.get(f"/api/v1/imagery/{row['id']}").json()["data"]
        assert data["preview_status"] == "failed" and data["thumbnail_url"] is None
    assert calls == [1]
    assert fake_supabase.store["imagery"][0]["metadata"]["raster"]["preview_error"] == raster_service.UNREADABLE_MESSAGE


def test_transient_download_failure_is_retried_later(client, fake_supabase):
    row = _legacy_row(fake_supabase, _geotiff())
    fake_supabase.storage.fail_next_download = True
    first = client.get(f"/api/v1/imagery/{row['id']}").json()["data"]
    assert first["preview_status"] is None and first["thumbnail_url"] is None
    second = client.get(f"/api/v1/imagery/{row['id']}").json()["data"]
    assert second["preview_status"] == "ready" and second["thumbnail_url"]


def test_conversation_detail_fills_older_previews(client, fake_supabase):
    conversation_id = client.post("/api/v1/conversations").json()["data"]["id"]
    _legacy_row(fake_supabase, _geotiff(), conversation_id=conversation_id)
    detail = client.get(f"/api/v1/conversations/{conversation_id}").json()["data"]
    assert detail["imagery"][0]["preview_status"] == "ready"
    assert detail["imagery"][0]["thumbnail_url"]


def test_without_migration_0007_previews_are_found_by_convention(client, fake_supabase, monkeypatch):
    row = _legacy_row(fake_supabase, _geotiff(), preview_status_column=False, with_thumbnail=PNG_SIGNATURE)
    calls = _count_extract_calls(monkeypatch)
    data = client.get(f"/api/v1/imagery/{row['id']}").json()["data"]
    assert data["thumbnail_url"] and calls == []
    assert "preview_status" not in fake_supabase.store["imagery"][0]  # nothing written to missing columns
