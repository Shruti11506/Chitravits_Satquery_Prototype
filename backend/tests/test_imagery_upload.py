from tests.images import real_jpeg, real_png, real_tiff


def _upload(client, filename="scene.jpg", content=None, content_type="image/jpeg", **form):
    content = real_jpeg() if content is None else content
    return client.post(
        "/api/v1/imagery/upload",
        files={"file": (filename, content, content_type)},
        data=form,
    )


def test_upload_imagery_success(client, fake_supabase):
    response = _upload(client, name="Bengaluru scene", source="Sentinel-2", sensor="MSI")
    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True

    data = body["data"]
    assert data["name"] == "Bengaluru scene"
    assert data["original_filename"] == "scene.jpg"
    assert data["bucket"] == "Satquery"
    assert data["storage_path"].startswith("imagery/")
    assert data["storage_path"].endswith("/scene.jpg")
    assert data["mime_type"] == "image/jpeg"
    assert data["file_size"] > 0

    # The file must actually have been uploaded to Storage, not just recorded in the DB.
    assert f"Satquery/{data['storage_path']}" in fake_supabase.storage.objects

    # And the imagery table must have a matching row.
    imagery_rows = fake_supabase.store["imagery"]
    assert len(imagery_rows) == 1
    assert imagery_rows[0]["storage_path"] == data["storage_path"]
    assert imagery_rows[0]["bucket"] == "Satquery"


def test_upload_imagery_defaults_name_to_filename(client):
    response = _upload(client, filename="unnamed_scene.png", content=real_png(), content_type="image/png")
    assert response.status_code == 201
    assert response.json()["data"]["name"] == "unnamed_scene.png"


def test_upload_imagery_accepts_geotiff(client):
    response = _upload(client, filename="raster.tif", content=real_tiff(), content_type="image/tiff")
    assert response.status_code == 201
    assert response.json()["data"]["mime_type"] == "image/tiff"


def test_upload_imagery_unsupported_file_type(client):
    response = _upload(client, filename="notes.txt", content=b"hello", content_type="text/plain")
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_upload_imagery_empty_file(client):
    response = _upload(client, content=b"")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EMPTY_FILE"


def test_upload_imagery_storage_failure_does_not_create_db_record(client, fake_supabase):
    fake_supabase.storage.fail_next_upload = True

    response = _upload(client)
    assert response.status_code == 500
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "STORAGE_UPLOAD_FAILED"

    assert fake_supabase.store.get("imagery", []) == []


def test_upload_imagery_supabase_side_size_rejection_is_classified_as_file_too_large(client, fake_supabase):
    """Our own pre-check already blocks anything over MAX_UPLOAD_SIZE_MB, but if
    Supabase's actual project-side limit is lower, Supabase itself rejects the
    upload -- that must be surfaced as FILE_TOO_LARGE, not a generic failure."""
    fake_supabase.storage.fail_next_upload_too_large = True

    response = _upload(client)
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "FILE_TOO_LARGE"

    assert fake_supabase.store.get("imagery", []) == []


def test_upload_imagery_invalid_metadata_json(client):
    response = _upload(client, metadata="{not valid json")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_METADATA"


def test_get_imagery_after_upload_includes_url(client):
    uploaded = _upload(client).json()["data"]

    response = client.get(f"/api/v1/imagery/{uploaded['id']}")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["storage_path"] == uploaded["storage_path"]
    assert data["bucket"] == "Satquery"
    # Satquery is private in the fake (mirrors the real project) -> signed URL, not a public one.
    assert data["url"] is not None
    assert "/sign/" in data["url"]


def test_delete_imagery_removes_storage_object(client, fake_supabase):
    uploaded = _upload(client).json()["data"]
    object_key = f"Satquery/{uploaded['storage_path']}"
    assert object_key in fake_supabase.storage.objects

    response = client.delete(f"/api/v1/imagery/{uploaded['id']}")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "deleted"

    assert object_key not in fake_supabase.storage.objects
    follow_up = client.get(f"/api/v1/imagery/{uploaded['id']}")
    assert follow_up.status_code == 404


def test_delete_imagery_blocked_by_referencing_job_leaves_everything_intact(client, fake_supabase):
    """The DB delete runs before the Storage delete, so a blocked DB delete
    (e.g. a foreign key violation from a referencing analysis_jobs row, as
    seen live against the real project) must leave both the record AND the
    Storage object untouched -- never an orphan on either side."""
    uploaded = _upload(client).json()["data"]
    object_key = f"Satquery/{uploaded['storage_path']}"
    fake_supabase.fail_next_table_delete.add("imagery")

    response = client.delete(f"/api/v1/imagery/{uploaded['id']}")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "SUPABASE_ERROR"

    assert client.get(f"/api/v1/imagery/{uploaded['id']}").status_code == 200
    assert object_key in fake_supabase.storage.objects


def test_delete_imagery_orphans_storage_object_if_storage_delete_fails_after_db_delete(client, fake_supabase):
    """DB delete succeeds, then Storage delete fails: the record is
    intentionally already gone (see imagery_service.delete_imagery), so the
    Storage object is orphaned and this is surfaced as an error rather than
    silently swallowed -- there's no cross-system transaction to roll back."""
    uploaded = _upload(client).json()["data"]
    fake_supabase.storage.fail_next_delete = True

    response = client.delete(f"/api/v1/imagery/{uploaded['id']}")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "STORAGE_ERROR"

    # The DB record is gone -- this is the documented tradeoff, not a bug.
    follow_up = client.get(f"/api/v1/imagery/{uploaded['id']}")
    assert follow_up.status_code == 404
