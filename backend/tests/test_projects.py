def test_list_projects_empty(client):
    response = client.get("/api/v1/projects")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"] == []


def test_create_and_get_project(client):
    # Create project
    create_resp = client.post(
        "/api/v1/projects",
        json={
            "name": "Sentinel-2 Flood Monitoring",
            "description": "Emergency flood response AOI",
            "icon": "🚨",
            "color": "#ef4444",
            "custom_instructions": "Prioritize NDWI inundation zone extraction.",
        },
    )
    assert create_resp.status_code == 201
    created = create_resp.json()["data"]
    assert created["name"] == "Sentinel-2 Flood Monitoring"
    assert created["description"] == "Emergency flood response AOI"
    assert created["has_custom_instructions"] is True
    assert created["chat_count"] == 0
    assert created["file_count"] == 0
    proj_id = created["id"]

    # List projects
    list_resp = client.get("/api/v1/projects")
    assert list_resp.status_code == 200
    projects = list_resp.json()["data"]
    assert len(projects) == 1
    assert projects[0]["id"] == proj_id

    # Get project detail
    detail_resp = client.get(f"/api/v1/projects/{proj_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert detail["id"] == proj_id
    assert detail["conversations"] == []
    assert detail["files"] == []


def test_update_and_delete_project(client):
    create_resp = client.post(
        "/api/v1/projects",
        json={"name": "Initial Name", "description": "Initial desc"},
    )
    proj_id = create_resp.json()["data"]["id"]

    # Update
    update_resp = client.patch(
        f"/api/v1/projects/{proj_id}",
        json={"name": "Updated Name", "custom_instructions": "New instructions"},
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()["data"]
    assert updated["name"] == "Updated Name"
    assert updated["has_custom_instructions"] is True

    # Delete
    del_resp = client.delete(f"/api/v1/projects/{proj_id}")
    assert del_resp.status_code == 200

    # Verify deleted
    get_resp = client.get(f"/api/v1/projects/{proj_id}")
    assert get_resp.status_code == 404


def test_project_file_upload_and_delete(client):
    create_resp = client.post(
        "/api/v1/projects",
        json={"name": "Project for Files"},
    )
    proj_id = create_resp.json()["data"]["id"]

    # Upload file
    file_resp = client.post(
        f"/api/v1/projects/{proj_id}/files",
        files={"file": ("test_aoi.geojson", b'{"type": "FeatureCollection"}', "application/json")},
    )
    assert file_resp.status_code == 201
    file_data = file_resp.json()["data"]
    assert file_data["name"] == "test_aoi.geojson"
    file_id = file_data["id"]

    # Detail shows file
    detail_resp = client.get(f"/api/v1/projects/{proj_id}")
    detail = detail_resp.json()["data"]
    assert detail["file_count"] == 1
    assert len(detail["files"]) == 1
    assert detail["files"][0]["id"] == file_id

    # Delete file
    del_file_resp = client.delete(f"/api/v1/projects/{proj_id}/files/{file_id}")
    assert del_file_resp.status_code == 200

    # Detail file_count is 0
    detail_resp2 = client.get(f"/api/v1/projects/{proj_id}")
    assert detail_resp2.json()["data"]["file_count"] == 0
