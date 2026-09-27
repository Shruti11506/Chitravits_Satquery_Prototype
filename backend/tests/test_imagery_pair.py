"""Image pair uploads (POST /imagery/pair) and pair-aware analysis requests."""
import io

from PIL import Image

from app.services import storage_service
from tests.fakes import FakeApiError
from tests.test_imagery_raster import _geotiff


def _rgb_bytes(fmt: str) -> bytes:
    # Real, decodable images (not just magic-byte-prefixed placeholders):
    # analysis_service's change-detection gate (see analysis_service.py)
    # actually opens these now, for a pair query. Same 8x8 size and modality
    # (plain RGB) for both, so a same-format/different-format pair is
    # otherwise a compatible pair by every OTHER check.
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(10, 20, 30)).save(buf, format=fmt)
    return buf.getvalue()


JPEG = _rgb_bytes("JPEG")
PNG = _rgb_bytes("PNG")


def _pair(client, first=("a.jpg", JPEG, "image/jpeg"), second=("b.png", PNG, "image/png"), **form):
    files = {}
    if first:
        files["image_1"] = first
    if second:
        files["image_2"] = second
    return client.post("/api/v1/imagery/pair", files=files, data=form)


def _conversation(client):
    return client.post("/api/v1/conversations").json()["data"]["id"]


def test_pair_upload_stores_two_independent_images(client, fake_supabase):
    conversation_id = _conversation(client)
    response = _pair(client, conversation_id=conversation_id)
    assert response.status_code == 201
    data = response.json()["data"]

    one, two = data["image_1"], data["image_2"]
    assert one["original_filename"] == "a.jpg" and two["original_filename"] == "b.png"
    assert one["pair_position"] == 1 and two["pair_position"] == 2
    assert one["pair_id"] == two["pair_id"] == data["pair_id"]
    assert one["storage_path"] != two["storage_path"]
    assert one["conversation_id"] == two["conversation_id"] == conversation_id

    # Two real Storage objects with the original bytes, at the usual path convention.
    assert fake_supabase.storage.objects[f"Satquery/{one['storage_path']}"] == JPEG
    assert fake_supabase.storage.objects[f"Satquery/{two['storage_path']}"] == PNG
    assert one["storage_path"].startswith("imagery/") and one["storage_path"].endswith("/a.jpg")

    rows = {row["id"]: row for row in fake_supabase.store["imagery"]}
    assert rows[one["id"]]["storage_path"] == one["storage_path"]
    assert rows[two["id"]]["pair_position"] == 2


def test_pair_of_geotiffs_gets_thumbnails_and_coordinates(client, fake_supabase):
    data = _pair(client, ("s2_a.tif", _geotiff(), "image/tiff"), ("s2_b.tif", _geotiff(), "image/tiff")).json()["data"]
    for image in (data["image_1"], data["image_2"]):
        assert image["thumbnail_url"]
        assert image["latitude"] is not None and image["bbox"]["crs"] == "EPSG:4326"
    assert len(fake_supabase.storage.objects) == 4  # two originals + two thumbnails


def test_pair_requires_both_images(client, fake_supabase):
    response = _pair(client, second=None)
    assert response.status_code == 422
    assert response.json()["error"] == {"code": "IMAGE_PAIR_INCOMPLETE", "message": "Please upload both images.", "details": None}
    assert fake_supabase.storage.objects == {}
    assert fake_supabase.store.get("imagery", []) == []


def test_invalid_second_image_stores_nothing(client, fake_supabase):
    response = _pair(client, second=("notes.txt", b"hello", "text/plain"))
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "UNSUPPORTED_FILE_TYPE"
    assert error["message"].startswith("Image 2:")
    assert fake_supabase.storage.objects == {}
    assert fake_supabase.store.get("imagery", []) == []


def test_empty_first_image_is_rejected(client, fake_supabase):
    response = _pair(client, first=("a.jpg", b"", "image/jpeg"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EMPTY_FILE"
    assert response.json()["error"]["message"].startswith("Image 1:")
    assert fake_supabase.storage.objects == {}


def test_second_storage_failure_removes_the_first_image(client, fake_supabase, monkeypatch):
    real_upload = storage_service.upload_file
    calls = []

    def flaky_upload(client_, path, content, content_type):
        calls.append(path)
        if len(calls) == 2:
            fake_supabase.storage.fail_next_upload = True
        return real_upload(client_, path, content, content_type)

    monkeypatch.setattr(storage_service, "upload_file", flaky_upload)
    response = _pair(client)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "STORAGE_UPLOAD_FAILED"
    assert fake_supabase.storage.objects == {}  # Image 1 was cleaned up
    assert fake_supabase.store.get("imagery", []) == []


def _failing_imagery_insert(fake_supabase, monkeypatch, code):
    real_table = fake_supabase.table

    class FailingInsert:
        def __init__(self, query):
            self.query = query

        def insert(self, rows):
            self.query.insert(rows)
            return self

        def execute(self):
            raise FakeApiError("insert failed", code)

    def table(name):
        query = real_table(name)
        return FailingInsert(query) if name == "imagery" else query

    monkeypatch.setattr(fake_supabase, "table", table)


def test_insert_failure_removes_both_uploaded_objects(client, fake_supabase, monkeypatch):
    _failing_imagery_insert(fake_supabase, monkeypatch, "XX000")
    response = _pair(client)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "SUPABASE_ERROR"
    assert fake_supabase.storage.objects == {}


def test_unmigrated_database_reports_the_migration(client, fake_supabase, monkeypatch):
    _failing_imagery_insert(fake_supabase, monkeypatch, "PGRST204")
    response = _pair(client)
    assert response.status_code == 503
    body = response.json()["error"]
    assert body["code"] == "SCHEMA_NOT_MIGRATED" and "0006_image_pairs.sql" in body["message"]
    assert fake_supabase.storage.objects == {}


def test_single_upload_rows_have_no_pair_fields(client, fake_supabase):
    response = client.post("/api/v1/imagery/upload", files={"file": ("one.jpg", JPEG, "image/jpeg")})
    assert response.status_code == 201
    row = fake_supabase.store["imagery"][0]
    assert "pair_id" not in row and "pair_position" not in row
    assert response.json()["data"]["pair_id"] is None


def test_pair_query_stores_both_image_ids(client, fake_supabase):
    # A pair that passes the change-detection compatibility gate
    # (analysis_service._reject_incompatible_pair) -- same modality (named
    # RGB bands), same dimensions, same CRS. A plain, non-georeferenced
    # visual pair (e.g. two JPEGs) would legitimately be rejected here; that
    # behaviour has its own dedicated tests (test_change_detection_validation.py).
    geotiff_rgb = ("s.tif", _geotiff(descriptions=["red", "green", "blue"]), "image/tiff")
    conversation_id = _conversation(client)
    pair = _pair(client, geotiff_rgb, geotiff_rgb, conversation_id=conversation_id).json()["data"]
    response = client.post("/api/v1/analysis", json={
        "imagery_id": pair["image_1"]["id"],
        "comparison_imagery_id": pair["image_2"]["id"],
        "analysis_type": "general_analysis",
        "query": "Compare these two images.",
        "conversation_id": conversation_id,
    })
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert data["imagery_id"] == pair["image_1"]["id"]
    assert data["comparison_imagery_id"] == pair["image_2"]["id"]

    job = fake_supabase.store["analysis_jobs"][0]
    assert job["imagery_id"] == pair["image_1"]["id"]
    assert job["comparison_imagery_id"] == pair["image_2"]["id"]
    assert job["query"] == "Compare these two images." and job["conversation_id"] == conversation_id
    assert job["status"] == "queued" and job.get("model_name") is None  # nothing ran

    history = client.get("/api/v1/analysis/history").json()["data"]
    assert history[0]["comparison_imagery_id"] == pair["image_2"]["id"]
    detail = client.get(f"/api/v1/conversations/{conversation_id}").json()["data"]
    assert detail["jobs"][0]["comparison_imagery_id"] == pair["image_2"]["id"]


def test_single_query_does_not_write_the_pair_column(client, fake_supabase):
    image = client.post("/api/v1/imagery/upload", files={"file": ("one.jpg", JPEG, "image/jpeg")}).json()["data"]
    response = client.post("/api/v1/analysis", json={
        "imagery_id": image["id"], "analysis_type": "general_analysis", "query": "What is here?",
    })
    assert response.status_code == 201
    assert response.json()["data"]["comparison_imagery_id"] is None
    assert "comparison_imagery_id" not in fake_supabase.store["analysis_jobs"][0]


def test_pair_query_rejects_same_image_twice(client):
    pair = _pair(client).json()["data"]
    response = client.post("/api/v1/analysis", json={
        "imagery_id": pair["image_1"]["id"], "comparison_imagery_id": pair["image_1"]["id"],
        "analysis_type": "general_analysis", "query": "Compare",
    })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_IMAGE_PAIR"


def test_pair_query_rejects_unknown_second_image(client):
    pair = _pair(client).json()["data"]
    response = client.post("/api/v1/analysis", json={
        "imagery_id": pair["image_1"]["id"], "comparison_imagery_id": "00000000-0000-0000-0000-000000000000",
        "analysis_type": "general_analysis", "query": "Compare",
    })
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "IMAGE_NOT_FOUND"


def test_pairs_stay_in_their_own_conversation(client):
    conversation_a, conversation_b = _conversation(client), _conversation(client)
    pair_a = _pair(client, ("a1.jpg", JPEG, "image/jpeg"), ("a2.jpg", JPEG, "image/jpeg"), conversation_id=conversation_a).json()["data"]
    pair_b = _pair(client, ("b1.jpg", JPEG, "image/jpeg"), ("b2.jpg", JPEG, "image/jpeg"), conversation_id=conversation_b).json()["data"]

    detail_a = client.get(f"/api/v1/conversations/{conversation_a}").json()["data"]
    detail_b = client.get(f"/api/v1/conversations/{conversation_b}").json()["data"]
    assert {i["id"] for i in detail_a["imagery"]} == {pair_a["image_1"]["id"], pair_a["image_2"]["id"]}
    assert {i["id"] for i in detail_b["imagery"]} == {pair_b["image_1"]["id"], pair_b["image_2"]["id"]}
    assert {(i["original_filename"], i["pair_position"]) for i in detail_a["imagery"]} == {("a1.jpg", 1), ("a2.jpg", 2)}


def test_deleting_the_conversation_removes_the_pair(client, fake_supabase):
    conversation_id = _conversation(client)
    pair = _pair(client, conversation_id=conversation_id).json()["data"]
    client.post("/api/v1/analysis", json={
        "imagery_id": pair["image_1"]["id"], "comparison_imagery_id": pair["image_2"]["id"],
        "analysis_type": "general_analysis", "query": "Compare", "conversation_id": conversation_id,
    })
    assert client.delete(f"/api/v1/conversations/{conversation_id}").status_code == 200
    assert fake_supabase.storage.objects == {}
    assert fake_supabase.store["imagery"] == [] and fake_supabase.store["analysis_jobs"] == []
