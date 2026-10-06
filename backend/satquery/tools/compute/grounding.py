"""Mock grounding tool (RGB extraction -> bounding boxes).

The real GeoGround model is not installed, so this produces *deterministic,
clearly-labelled* boxes so the grounding pipeline (RGB extraction → boxes →
geo-referenced detections → evidence → map) runs end-to-end. It is marked
``backend="mock"``/``model="geoground"`` so the Evidence Engine flags it as a
demo output and never claims a real detector ran (spec §48, §56).

Pixel boxes are converted to geographic coordinates via the raster transform
when a CRS exists; without one, only pixel boxes are reported.
"""

from __future__ import annotations

import time

from satquery.tools.raster import meta_of, open_raster
from satquery.tools.schemas import SpatialResult, ToolResult, ToolStatus

# Deterministic normalized boxes (x0, y0, x1, y1) in [0, 1].
_MOCK_BOXES = [(0.12, 0.18, 0.34, 0.42), (0.55, 0.60, 0.80, 0.86), (0.40, 0.05, 0.52, 0.20)]


def _pixel_to_geo(transform, col: float, row: float) -> tuple[float, float]:
    from rasterio.transform import xy

    x, y = xy(transform, row, col, offset="ul")
    return float(x), float(y)


def run_grounding(source, profile, *, label: str = "object") -> ToolResult:
    """Return deterministic detections as a ToolResult (mock GeoGround)."""
    t0 = time.perf_counter()
    try:
        with open_raster(source) as ds:
            meta = meta_of(ds)
            w, h = ds.width, ds.height
            transform = ds.transform
    except Exception as exc:  # noqa: BLE001
        return ToolResult(tool_name="geoground", status=ToolStatus.FAILED,
                          execution_time_ms=0, errors=[f"grounding failed: {exc}"],
                          metadata={"error_code": "GROUNDING_FAILED"})

    spatial: list[SpatialResult] = []
    for i, (x0, y0, x1, y1) in enumerate(_MOCK_BOXES):
        px = [x0 * w, y0 * h, x1 * w, y1 * h]
        geo_bbox = None
        if meta.crs:
            gx0, gy0 = _pixel_to_geo(transform, px[0], px[3])  # lower-left
            gx1, gy1 = _pixel_to_geo(transform, px[2], px[1])  # upper-right
            geo_bbox = [gx0, gy0, gx1, gy1]
        spatial.append(SpatialResult(
            region_id=f"{label}_{i}", bbox=px, confidence=round(0.75 + 0.05 * i, 2),
            source_tool="geoground",
        ))
        if geo_bbox:
            spatial[-1].change_type = None  # keep field usage explicit; geo stored below
    elapsed = int((time.perf_counter() - t0) * 1000)

    return ToolResult(
        tool_name="geoground", status=ToolStatus.SUCCESS, execution_time_ms=elapsed,
        answer=f"Detected {len(spatial)} candidate region(s) for '{label}'.",
        spatial_results=spatial,
        metadata={
            "backend": "mock", "model": "geoground", "label": label,
            "crs": meta.crs, "image_size": [w, h],
        },
    )
