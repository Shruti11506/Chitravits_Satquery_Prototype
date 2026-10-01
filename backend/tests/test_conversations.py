import pytest

from app.services.title_service import generate_conversation_title
from tests.images import real_tiff


def _new_conversation(client):
    response = client.post("/api/v1/conversations")
    assert response.status_code == 201
    return response.json()["data"]


def _upload(client, conversation_id, filename="S2A_MSIL2A_20230804_004E043.tif"):
    return client.post(
        "/api/v1/imagery/upload",
        files={"file": (filename, real_tiff(), "image/tiff")},
        data={"name": filename, "conversation_id": conversation_id},
    )


def _ask(client, conversation_id, imagery_id, query):
    return client.post(
        "/api/v1/analysis",
        json={
            "imagery_id": imagery_id,
            "analysis_type": "general_analysis",
            "query": query,
            "conversation_id": conversation_id,
        },
    )


def _title(client, conversation_id):
    return client.get(f"/api/v1/conversations/{conversation_id}").json()["data"]["title"]


@pytest.mark.parametrize(
    "query, expected",
    [
        ("Highlight water bodies", "Water Body Detection"),
        ("Identify water bodies in this satellite image", "Water Body Detection"),
        ("Compare optical and SAR imagery", "Optical vs SAR Analysis"),
        ("Compare this optical image with SAR and identify changes", "Optical vs SAR Change Analysis"),
        ("Identify flood affected areas", "Flood Impact Analysis"),
        ("Detect flood-affected regions", "Flood Impact Detection"),
        ("Find urban expansion in this image", "Urban Expansion Analysis"),
        ("Analyze vegetation health", "Vegetation Health Analysis"),
        ("Highlight water bodies and calculate urban growth", "Water Bodies & Urban Growth"),
        ("Detect 5-year bi-temporal urban & water changes", "Urban & Water Change Detection"),
        ("Identify all road networks and industrial clusters", "Road Networks & Industrial Areas"),
        ("Describe this satellite scene in detail", "Scene Description"),
        ("Detect building structures using SAR double-bounce radar backscatter", "SAR Building Detection"),
        ("Compare these two images.", "Image Comparison"),
        ("What are the differences between these satellite images?", "Image Comparison"),
        ("Compare vegetation in both images", "Vegetation Analysis"),
    ],
)
def test_generate_conversation_title(query, expected):
    assert generate_conversation_title(query) == expected


@pytest.mark.parametrize("query", ["", "   ", "hi", "ok!", "thanks", "??"])
def test_trivial_queries_produce_no_title(query):
    assert generate_conversation_title(query) is None


def test_fallback_title_never_contains_filenames_uuids_or_numbers():
    title = generate_conversation_title(
        "Summarise S2A_MSIL2A_20230804_004E043.tif 3fa85f64-5717-4562-b3fc-2c963f66afa6 please"
    )
    assert title == "Scene Description"
    title = generate_conversation_title("estimate snow depth for sentinel_image_001.tif in 2023")
    assert title is not None
    assert ".tif" not in title and "2023" not in title and "_" not in title
    assert 2 <= len(title.split()) <= 6


def test_new_conversation_is_titled_new_chat(client):
    conversation = _new_conversation(client)
    assert conversation["title"] == "New Chat"
    assert conversation["title_source"] == "default"


def test_acceptance_upload_keeps_new_chat_then_first_query_titles_it(client):
    """Test 1 + Test 4 from the spec: upload never renames; first query titles
    the chat; later queries never rename it."""
    conversation = _new_conversation(client)
    cid = conversation["id"]

    upload = _upload(client, cid)
    assert upload.status_code == 201
    imagery_id = upload.json()["data"]["id"]
    assert upload.json()["data"]["conversation_id"] == cid

    # Even an explicit title-generation call after the upload must not use the filename.
    client.post(f"/api/v1/conversations/{cid}/title")
    assert _title(client, cid) == "New Chat"

    assert _ask(client, cid, imagery_id, "Highlight water bodies").status_code == 201
    titled = client.post(f"/api/v1/conversations/{cid}/title").json()["data"]
    assert titled["title"] == "Water Body Detection"
    assert titled["title_source"] == "auto"

    assert _ask(client, cid, imagery_id, "Now calculate their area").status_code == 201
    client.post(f"/api/v1/conversations/{cid}/title")
    assert _title(client, cid) == "Water Body Detection"


def test_title_skips_leading_trivial_messages(client):
    cid = _new_conversation(client)["id"]
    imagery_id = _upload(client, cid).json()["data"]["id"]
    _ask(client, cid, imagery_id, "hi")
    client.post(f"/api/v1/conversations/{cid}/title")
    assert _title(client, cid) == "New Chat"

    _ask(client, cid, imagery_id, "Identify flood affected areas")
    client.post(f"/api/v1/conversations/{cid}/title")
    assert _title(client, cid) == "Flood Impact Analysis"


def test_user_rename_is_never_overwritten(client):
    cid = _new_conversation(client)["id"]
    imagery_id = _upload(client, cid).json()["data"]["id"]

    renamed = client.patch(f"/api/v1/conversations/{cid}", json={"title": "  My   flood study "})
    assert renamed.status_code == 200
    assert renamed.json()["data"]["title"] == "My flood study"
    assert renamed.json()["data"]["title_source"] == "user"

    _ask(client, cid, imagery_id, "Compare optical and SAR imagery")
    client.post(f"/api/v1/conversations/{cid}/title")
    assert _title(client, cid) == "My flood study"


def test_rename_rejects_blank_title(client):
    cid = _new_conversation(client)["id"]
    response = client.patch(f"/api/v1/conversations/{cid}", json={"title": "   "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_TITLE"


def test_detail_returns_uploads_and_queries_oldest_first(client):
    cid = _new_conversation(client)["id"]
    imagery_id = _upload(client, cid, filename="sentinel_image_001.tif").json()["data"]["id"]
    _ask(client, cid, imagery_id, "First")
    _ask(client, cid, imagery_id, "Second")

    detail = client.get(f"/api/v1/conversations/{cid}").json()["data"]
    assert [i["original_filename"] for i in detail["imagery"]] == ["sentinel_image_001.tif"]
    assert detail["imagery"][0]["url"]
    assert [j["query"] for j in detail["jobs"]] == ["First", "Second"]
    assert all(j["conversation_id"] == cid for j in detail["jobs"])


def test_list_conversations_most_recently_active_first(client):
    first = _new_conversation(client)["id"]
    second = _new_conversation(client)["id"]
    _upload(client, second)
    # Later activity in the first conversation bumps it above the second.
    _upload(client, first)

    ids = [c["id"] for c in client.get("/api/v1/conversations").json()["data"]]
    assert ids == [first, second]


def test_empty_conversations_are_not_listed(client):
    empty = _new_conversation(client)["id"]
    uploaded = _new_conversation(client)["id"]
    _upload(client, uploaded)
    asked = _new_conversation(client)["id"]
    imagery_id = _upload(client, asked).json()["data"]["id"]
    _ask(client, asked, imagery_id, "Highlight water bodies")

    ids = {c["id"] for c in client.get("/api/v1/conversations").json()["data"]}
    assert ids == {uploaded, asked}
    # Still stored and reachable directly -- hidden, not deleted.
    assert client.get(f"/api/v1/conversations/{empty}").status_code == 200


def _age(fake_supabase, conversation_id, minutes):
    from datetime import datetime, timedelta, timezone

    row = next(r for r in fake_supabase.store["conversations"] if r["id"] == conversation_id)
    row["created_at"] = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def test_purge_empty_conversations_dry_run_then_apply(client, fake_supabase):
    from app.services.conversation_service import purge_empty_conversations

    old_empty = _new_conversation(client)["id"]
    recent_empty = _new_conversation(client)["id"]
    old_started = _new_conversation(client)["id"]
    _upload(client, old_started)
    _age(fake_supabase, old_empty, 120)
    _age(fake_supabase, old_started, 120)

    assert [r["id"] for r in purge_empty_conversations(60)] == [old_empty]
    assert client.get(f"/api/v1/conversations/{old_empty}").status_code == 200  # dry run

    assert [r["id"] for r in purge_empty_conversations(60, apply=True)] == [old_empty]
    assert client.get(f"/api/v1/conversations/{old_empty}").status_code == 404
    # A recent empty one may have its first upload in flight; never touched.
    assert client.get(f"/api/v1/conversations/{recent_empty}").status_code == 200
    assert client.get(f"/api/v1/conversations/{old_started}").status_code == 200


def test_unknown_conversation_is_404(client):
    missing = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    for response in (
        client.get(f"/api/v1/conversations/{missing}"),
        client.patch(f"/api/v1/conversations/{missing}", json={"title": "x"}),
        client.post(f"/api/v1/conversations/{missing}/title"),
        client.delete(f"/api/v1/conversations/{missing}"),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_upload_to_unknown_conversation_stores_nothing(client, fake_supabase):
    response = _upload(client, "3fa85f64-5717-4562-b3fc-2c963f66afa6")
    assert response.status_code == 404
    assert fake_supabase.storage.objects == {}
    assert fake_supabase.store.get("imagery", []) == []


def test_delete_conversation_removes_queries_uploads_and_files(client, fake_supabase):
    cid = _new_conversation(client)["id"]
    imagery_id = _upload(client, cid).json()["data"]["id"]
    _ask(client, cid, imagery_id, "Highlight water bodies")

    other = _new_conversation(client)["id"]
    other_imagery = _upload(client, other, filename="keep.tif").json()["data"]["id"]
    _ask(client, other, other_imagery, "Analyze vegetation health")

    response = client.delete(f"/api/v1/conversations/{cid}")
    assert response.status_code == 200

    assert client.get(f"/api/v1/conversations/{cid}").status_code == 404
    assert [j["conversation_id"] for j in fake_supabase.store["analysis_jobs"]] == [other]
    assert [i["id"] for i in fake_supabase.store["imagery"]] == [other_imagery]
    # Only the kept upload's objects remain: its original and (real TIFF) its preview.
    kept = [k for k in fake_supabase.storage.objects if k.endswith("/keep.tif")]
    assert len(kept) == 1
    kept_folder = kept[0].rsplit("/", 1)[0]
    assert all(k.startswith(kept_folder + "/") for k in fake_supabase.storage.objects)


def _add_result(fake_supabase, job_id):
    """A completed job's result + evidence, as the model worker writes them."""
    result_id = f"r-{job_id}"
    fake_supabase.store.setdefault("analysis_results", []).append(
        {"id": result_id, "job_id": job_id, "analysis_type": "vqa"}
    )
    fake_supabase.store.setdefault("evidence", []).append(
        {"id": f"e-{job_id}", "result_id": result_id, "evidence_type": "bbox"}
    )


def test_delete_conversation_removes_results_and_evidence_of_completed_jobs(client, fake_supabase):
    cid = _new_conversation(client)["id"]
    imagery_id = _upload(client, cid).json()["data"]["id"]
    job_id = _ask(client, cid, imagery_id, "Highlight water bodies").json()["data"]["job_id"]
    _add_result(fake_supabase, job_id)

    other = _new_conversation(client)["id"]
    other_imagery = _upload(client, other, filename="keep.tif").json()["data"]["id"]
    other_job = _ask(client, other, other_imagery, "Analyze vegetation").json()["data"]["job_id"]
    _add_result(fake_supabase, other_job)

    assert client.delete(f"/api/v1/conversations/{cid}").status_code == 200

    assert [r["job_id"] for r in fake_supabase.store["analysis_results"]] == [other_job]
    assert [e["result_id"] for e in fake_supabase.store["evidence"]] == [f"r-{other_job}"]


def _legacy_chat(client, name="legacy"):
    imagery_id = client.post("/api/v1/imagery", json={"name": name}).json()["data"]["id"]
    job = client.post(
        "/api/v1/analysis",
        json={"imagery_id": imagery_id, "analysis_type": "vqa", "query": "Old style"},
    ).json()["data"]
    return imagery_id, job["job_id"]


def test_delete_legacy_chat_removes_its_queries_results_and_image(client, fake_supabase):
    imagery_id, job_id = _legacy_chat(client)
    _add_result(fake_supabase, job_id)
    kept_imagery, kept_job = _legacy_chat(client, name="keep")

    response = client.delete(f"/api/v1/conversations/legacy/{imagery_id}")
    assert response.status_code == 200

    assert [j["id"] for j in fake_supabase.store["analysis_jobs"]] == [kept_job]
    assert [i["id"] for i in fake_supabase.store["imagery"]] == [kept_imagery]
    assert fake_supabase.store["analysis_results"] == []
    assert fake_supabase.store["evidence"] == []


def test_rename_legacy_chat_turns_it_into_a_conversation(client, fake_supabase):
    imagery_id, job_id = _legacy_chat(client)
    other_imagery, other_job = _legacy_chat(client, name="other")

    response = client.patch(f"/api/v1/conversations/legacy/{imagery_id}", json={"title": "  My  scene "})
    assert response.status_code == 200
    conversation = response.json()["data"]
    assert conversation["title"] == "My scene"
    assert conversation["title_source"] == "user"

    jobs = {j["id"]: j.get("conversation_id") for j in fake_supabase.store["analysis_jobs"]}
    assert jobs == {job_id: conversation["id"], other_job: None}
    images = {i["id"]: i.get("conversation_id") for i in fake_supabase.store["imagery"]}
    assert images == {imagery_id: conversation["id"], other_imagery: None}
    # It is now an ordinary conversation, listed with its new title.
    listed = client.get("/api/v1/conversations").json()["data"]
    assert [c["title"] for c in listed] == ["My scene"]


def test_rename_legacy_chat_rejects_blank_title(client, fake_supabase):
    imagery_id, _ = _legacy_chat(client)
    response = client.patch(f"/api/v1/conversations/legacy/{imagery_id}", json={"title": "   "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_TITLE"
    assert fake_supabase.store.get("conversations", []) == []


def test_delete_legacy_chat_ignores_conversation_queries(client, fake_supabase):
    cid = _new_conversation(client)["id"]
    imagery_id = _upload(client, cid).json()["data"]["id"]
    _ask(client, cid, imagery_id, "Highlight water bodies")

    response = client.delete(f"/api/v1/conversations/legacy/{imagery_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CHAT_NOT_FOUND"
    assert len(fake_supabase.store["analysis_jobs"]) == 1
    assert len(fake_supabase.store["imagery"]) == 1


def test_legacy_requests_without_conversation_still_work(client):
    imagery_id = client.post("/api/v1/imagery", json={"name": "legacy"}).json()["data"]["id"]
    response = client.post(
        "/api/v1/analysis",
        json={"imagery_id": imagery_id, "analysis_type": "vqa", "query": "Old style"},
    )
    assert response.status_code == 201
    assert response.json()["data"]["conversation_id"] is None
    history = client.get("/api/v1/analysis/history").json()["data"]
    assert history[0]["conversation_id"] is None
