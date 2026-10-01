import base64
import re
import zlib
from datetime import datetime

from app.services.report_service import safe_filename
from tests.images import real_png, real_tiff


def _pdf_text(pdf: bytes) -> str:
    """Text drawn on the PDF's pages (reportlab compresses each page stream)."""
    chunks = []
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        for decode in (lambda b: b, lambda b: base64.a85decode(b.strip(), adobe=True)):  # Flate or ASCII85+Flate
            try:
                chunks.append(zlib.decompress(decode(raw)).decode("latin-1"))
                break
            except (zlib.error, ValueError):
                continue
    # Text-showing operators: "(text) Tj"; join so phrases split across runs still match.
    return " ".join(m.replace("\\(", "(").replace("\\)", ")") for m in re.findall(r"\((.*?)(?<!\\)\)\s*Tj", "\n".join(chunks)))


def _conversation_with_query(client, query="Detect buildings in this satellite image"):
    cid = client.post("/api/v1/conversations").json()["data"]["id"]
    upload = client.post(
        "/api/v1/imagery/upload",
        files={"file": ("scene.png", real_png(64, 48), "image/png")},
        data={"name": "scene.png", "conversation_id": cid},
    ).json()["data"]
    job = client.post(
        "/api/v1/analysis",
        json={"imagery_id": upload["id"], "analysis_type": "general_analysis", "query": query, "conversation_id": cid},
    ).json()["data"]
    return cid, upload["id"], job["job_id"]


def test_report_of_a_completed_query_contains_the_real_query_result_and_output_image(client, fake_supabase):
    cid, _, job_id = _conversation_with_query(client)
    fake_supabase.storage.objects["Satquery/results/mask.png"] = real_png(40, 40)
    fake_supabase.store.setdefault("analysis_results", []).append(
        {
            "id": "res-1",
            "job_id": job_id,
            "answer": "Three building clusters were found in the north-east.",
            "confidence": 0.87,
            "model_name": "EarthMind-4B",
            "analysis_type": "vqa",
            "raw_output": {"outputs": {"building_count": 3}},
        }
    )
    fake_supabase.store.setdefault("evidence", []).append(
        {"id": "ev-1", "result_id": "res-1", "evidence_type": "segmentation_mask",
         "description": "Built-up mask", "source_reference": "results/mask.png", "confidence": 0.9}
    )

    response = client.post("/api/v1/reports", json={"conversation_id": cid, "attached_model": "YOLOv8x-Satellite-Urban"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert re.match(r'attachment; filename="SatQuery_Analysis_Report_[A-Za-z0-9_]+_\d{4}-\d{2}-\d{2}\.pdf"',
                    response.headers["content-disposition"])
    pdf = response.content
    assert pdf.startswith(b"%PDF")
    text = _pdf_text(pdf)
    assert "SatQuery" in text
    assert "Detect buildings in this satellite image" in text
    assert "Three building clusters were found" in text
    assert "EarthMind-4B" in text
    assert "87.0%" in text
    assert "Building count" in text
    assert "YOLOv8x-Satellite-Urban" in text
    assert job_id[:8] in text
    assert "Page 1 of" in text
    # Input image + the stored output visualization are embedded.
    assert pdf.count(b"/Subtype /Image") >= 2


def test_report_of_a_queued_query_says_result_not_available(client, fake_supabase):
    cid, _, _ = _conversation_with_query(client, query="Highlight water bodies")
    response = client.post("/api/v1/reports", json={"conversation_id": cid})
    assert response.status_code == 200
    text = _pdf_text(response.content)
    assert "Highlight water bodies" in text
    assert "Result not available" in text
    assert "queued" in text
    assert "Model response" not in text


def test_report_embeds_a_tiff_through_its_preview(client, fake_supabase):
    cid = client.post("/api/v1/conversations").json()["data"]["id"]
    client.post(
        "/api/v1/imagery/upload",
        files={"file": ("S2A_scene.tif", real_tiff(32, 24), "image/tiff")},
        data={"name": "S2A_scene.tif", "conversation_id": cid},
    )
    response = client.post("/api/v1/reports", json={"conversation_id": cid})
    assert response.status_code == 200
    assert b"/Subtype /Image" in response.content
    text = _pdf_text(response.content)
    assert "S2A_scene.tif" in text
    assert "Sentinel-2" in text


def test_report_of_a_legacy_chat(client, fake_supabase):
    imagery_id = client.post("/api/v1/imagery", json={"name": "legacy"}).json()["data"]["id"]
    client.post("/api/v1/analysis", json={"imagery_id": imagery_id, "analysis_type": "vqa", "query": "Old style query"})
    response = client.post("/api/v1/reports", json={"imagery_id": imagery_id})
    assert response.status_code == 200
    text = _pdf_text(response.content)
    assert "Old style query" in text


def test_report_needs_a_target(client):
    response = client.post("/api/v1/reports", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REPORT_TARGET_REQUIRED"


def test_report_of_unknown_conversation_is_404(client):
    response = client.post("/api/v1/reports", json={"conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"})
    assert response.status_code == 404


def test_report_filename_is_sanitized():
    name = safe_filename('SAR / Building "Detection" <test>', datetime(2026, 10, 1))
    assert name == "SatQuery_Analysis_Report_SAR_Building_Detection_test_2026-10-01.pdf"
