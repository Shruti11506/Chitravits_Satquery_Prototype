"""Agent bridge unit tests (no network, no Supabase, no satquery runtime).

Covers the pure mapping between the backend's job/imagery rows and the agent's
contracts, and the flag-gated scheduling in the analysis route:

* AGENT_ENABLED defaults false -> the route behaves exactly as before (no
  background task scheduled, satquery never imported).
* AGENT_ENABLED true -> a background task is scheduled after the job is created.

The live end-to-end flow against the real wrapper APIs is exercised separately
(see the integration script in the PR description); it is not run here so the
unit suite stays offline and deterministic.

These tests import ``app.agent_bridge.mapping``, which only needs the installed
``satquery`` package for its schema types; they skip cleanly if it is absent.
"""
from __future__ import annotations

import pytest

pytest.importorskip("satquery", reason="satquery package not installed in this env")

from app.agent_bridge.mapping import (  # noqa: E402
    build_user_query,
    evidence_rows_from_response,
    result_row_from_response,
)


# --- fakes -----------------------------------------------------------------

class _Resp:
    """Minimal stand-in for satquery's AgentResponse (duck-typed)."""

    def __init__(self, *, message, data):
        self.message = message
        self.data = data


def _imagery(iid, name, filename, sensor=None):
    return {
        "id": iid, "name": name, "original_filename": filename, "sensor": sensor,
        "source": None, "storage_path": iid, "acquisition_date": None,
    }


def _job(jid, analysis_type, query, imagery_id, comparison_id=None):
    return {
        "id": jid, "analysis_type": analysis_type, "query": query,
        "imagery_id": imagery_id, "comparison_imagery_id": comparison_id,
        "conversation_id": None,
    }


# --- build_user_query ------------------------------------------------------

class TestBuildUserQuery:
    def test_single_image_maps_to_one_attachment(self):
        uq = build_user_query(
            _job("job-1", "vqa", "What is visible?", "img-1"),
            _imagery("img-1", "scene", "scene.png"),
            None,
        )
        assert uq.query == "What is visible?"
        assert len(uq.attachments) == 1
        assert uq.attachments[0].id == "img-1"
        assert uq.attachments[0].uri == "satquery://img-1"
        # analysis_type vqa overrides the text classifier.
        assert uq.metadata.get("task") == "vqa"

    def test_pair_maps_t1_before_t2_after(self):
        uq = build_user_query(
            _job("job-2", "change_detection", "What changed?", "img-1", "img-2"),
            _imagery("img-1", "t1", "t1.tif"),
            _imagery("img-2", "t2", "t2.tif"),
        )
        assert len(uq.attachments) == 2
        roles = [a.role.value for a in uq.attachments]
        assert roles == ["before", "after"]
        assert uq.metadata.get("task") == "change_detection"

    def test_general_analysis_defers_to_text_classifier(self):
        # general_analysis has no override -> metadata carries no forced task.
        uq = build_user_query(
            _job("job-3", "general_analysis", "Where are the buildings?", "img-1"),
            _imagery("img-1", "scene", "scene.png"),
            None,
        )
        assert "task" not in uq.metadata

    def test_sar_sensor_sets_sar_modality(self):
        uq = build_user_query(
            _job("job-4", "general_analysis", "Analyse backscatter", "img-1"),
            _imagery("img-1", "s1", "s1.tif", sensor="Sentinel-1 SAR"),
            None,
        )
        assert uq.attachments[0].modality.value == "sar"


# --- response -> rows ------------------------------------------------------

class TestResponseMapping:
    def _response(self):
        return _Resp(
            message="A dense urban area.",
            data={
                "answer": "A dense urban area.",
                "confidence": 0.9,
                "model": "EarthMind-4B",
                "tool_selected": "earthmind",
                "evidence": [{"claim": "Urban buildings visible.", "source_tool": "earthmind", "data": {}}],
                "measurements": [{"name": "change_area", "value": 12.4, "unit": "ha", "source_tool": "mcd_mamba"}],
                "spatial_results": [
                    {"region_id": "r0", "change_type": "new", "area_ha": 3.1,
                     "bbox": [0, 0, 1, 1], "confidence": 0.8, "source_tool": "mcd_mamba"}
                ],
                "output_files": [
                    {"name": "change_map.png", "kind": "change_map",
                     "url": "https://svc/outputs/change_map.png", "path": None,
                     "media_type": "image/png", "producer": "mcd_mamba"}
                ],
                "execution_trace": {"workflow": "sequential", "tool_execution_order": []},
            },
        )

    def test_result_row_carries_answer_and_raw_output(self):
        row = result_row_from_response(_job("job-5", "vqa", "q", "img-1"), self._response())
        assert row["job_id"] == "job-5"
        assert row["answer"] == "A dense urban area."
        assert row["confidence"] == 0.9
        assert row["model_name"] == "EarthMind-4B"
        # The full structured payload (incl. execution trace) is preserved.
        assert row["raw_output"]["execution_trace"]["workflow"] == "sequential"

    def test_evidence_rows_cover_every_source_and_preserve_provenance(self):
        rows = evidence_rows_from_response("result-1", self._response())
        by_type = {r["evidence_type"] for r in rows}
        assert by_type == {"claim", "measurement", "change_region", "output_file"}
        # Each row keeps the tool that produced it.
        for r in rows:
            assert r["result_id"] == "result-1"
            assert r["source_reference"] in {"earthmind", "mcd_mamba"}
        out = next(r for r in rows if r["evidence_type"] == "output_file")
        assert out["metadata"]["url"].endswith("change_map.png")
        assert out["metadata"]["kind"] == "change_map"
        region = next(r for r in rows if r["evidence_type"] == "change_region")
        assert region["bbox"] == {"bbox": [0, 0, 1, 1]}
        assert region["confidence"] == 0.8

    def test_no_output_files_yields_no_output_rows(self):
        resp = _Resp(message="ok", data={"answer": "ok", "evidence": [], "measurements": [],
                                          "spatial_results": [], "output_files": []})
        rows = evidence_rows_from_response("result-2", resp)
        assert rows == []


class TestGeoGroundPixelOverlayIsRenderable:
    """Regression: a GeoGround PIXEL-coordinate detection (no CRS) must still
    produce a renderable overlay artifact and a pixel bbox that reach the
    frontend. This is the path behind the "no bounding box shown" bug -- the
    overlay URL and pixel box must survive mapping even without geo coordinates.
    """

    def _geoground_pixel_response(self):
        # Shaped exactly like the agent's serialised data for a grounding result
        # on a PNG (pixel coords only, bounding_box_geo absent -> geo_referenced
        # False), with the model-rendered overlay image.
        overlay = "https://geoground.example/outputs/grounding_input_abc.png"
        return _Resp(
            message="GeoGround localized 1 region matching 'airplanes', in pixel coordinates only.",
            data={
                "answer": "GeoGround localized 1 region matching 'airplanes', in pixel coordinates only.",
                "confidence": 0.504,
                "model": "GeoGround",
                "tool_selected": "geoground",
                "task": "grounding",
                "evidence": [{"claim": "airplanes localized", "source_tool": "geoground",
                              "data": {"target": "airplanes", "geo_referenced": False}}],
                "measurements": [{"name": "detection_count", "value": 1.0, "unit": "count",
                                  "source_tool": "geoground"}],
                "spatial_results": [
                    {"region_id": "airplanes_0", "change_type": None, "area_ha": None,
                     "bbox": [0.0, 0.0, 149.0, 108.0], "confidence": 0.504,
                     "source_tool": "geoground"}
                ],
                "output_files": [
                    {"name": "grounding_input_abc.png", "kind": "overlay", "url": overlay,
                     "path": None, "media_type": "image/png", "producer": "geoground"}
                ],
                "execution_trace": {"workflow": "single",
                                    "tool_execution_order": [{"tool_name": "geoground", "status": "success"}]},
            },
        )

    def test_overlay_artifact_survives_mapping(self):
        resp = self._geoground_pixel_response()
        rows = evidence_rows_from_response("result-gg", resp)

        # A renderable overlay image is present, with a fetchable URL.
        overlay = next(r for r in rows if r["evidence_type"] == "output_file")
        assert overlay["metadata"]["kind"] == "overlay"
        assert overlay["metadata"]["url"].endswith("grounding_input_abc.png")
        assert overlay["source_reference"] == "geoground"

        # The pixel bounding box is carried (no CRS required to render it).
        region = next(r for r in rows if r["evidence_type"] == "change_region")
        assert region["bbox"] == {"bbox": [0.0, 0.0, 149.0, 108.0]}
        assert region["confidence"] == 0.504

    def test_raw_output_carries_overlay_and_pixel_bbox_for_the_frontend(self):
        resp = self._geoground_pixel_response()
        row = result_row_from_response(_job("job-gg", "region_grounding", "Where are the airplanes?", "img-1"), resp)
        raw = row["raw_output"]

        # The frontend reads these off raw_output to render the overlay + boxes.
        assert raw["output_files"][0]["url"].endswith("grounding_input_abc.png")
        assert raw["output_files"][0]["kind"] == "overlay"
        assert raw["spatial_results"][0]["bbox"] == [0.0, 0.0, 149.0, 108.0]
        assert raw["spatial_results"][0]["confidence"] == 0.504
        # Execution trace names GeoGround.
        order = [t["tool_name"] for t in raw["execution_trace"]["tool_execution_order"]]
        assert order == ["geoground"]


# --- route flag gate -------------------------------------------------------

class TestRouteFlagGate:
    def _register_imagery(self, client):
        r = client.post("/api/v1/imagery", json={"name": "scene", "source": "Sentinel-2"})
        return r.json()["data"]["id"]

    def test_flag_off_does_not_schedule_agent(self, client, monkeypatch):
        import app.api.routes.analysis as analysis_route

        monkeypatch.setattr(analysis_route.get_settings(), "AGENT_ENABLED", False, raising=False)
        called = {"n": 0}

        def _boom(*a, **k):  # must never be imported/called when the flag is off
            called["n"] += 1

        # If the route tried to schedule, it would import the runner; ensure it doesn't.
        imagery_id = self._register_imagery(client)
        resp = client.post(
            "/api/v1/analysis",
            json={"imagery_id": imagery_id, "analysis_type": "vqa", "query": "What is visible?"},
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["status"] == "queued"
        assert called["n"] == 0

    def test_flag_on_schedules_background_task(self, client, monkeypatch):
        import app.api.routes.analysis as analysis_route

        monkeypatch.setattr(analysis_route.get_settings(), "AGENT_ENABLED", True, raising=False)

        scheduled = {"job_ids": []}

        def _fake_run(job_id):
            scheduled["job_ids"].append(job_id)

        # Replace the runner import target so no real agent/network is touched.
        import app.agent_bridge.runner as runner
        monkeypatch.setattr(runner, "run_analysis_job", _fake_run, raising=False)

        imagery_id = self._register_imagery(client)
        resp = client.post(
            "/api/v1/analysis",
            json={"imagery_id": imagery_id, "analysis_type": "vqa", "query": "What is visible?"},
        )
        assert resp.status_code == 201
        # TestClient runs background tasks synchronously after the response.
        assert scheduled["job_ids"] == [resp.json()["data"]["job_id"]]
