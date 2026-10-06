"""Build the VLM context string passed to EarthMind.

This is the only place that converts DataProfile / AOIContext objects into
model-facing text.  It lives here (not in DataProfile) so the schema stays
clean and model-specific prompting can evolve independently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from satquery.preprocessor.schemas import AOIContext, DataProfile


def build_vlm_context(
    profiles: list["DataProfile"],
    user_query: str,
    aoi_contexts: list["AOIContext"] | None = None,
) -> str:
    """Compose a VLM-ready context string from preprocessed profiles.

    When no profiles are available the raw ``user_query`` is returned unchanged
    so the EarthMind call still works as a plain VQA.
    """
    if not profiles and not aoi_contexts:
        return user_query

    sections: list[str] = []

    for i, p in enumerate(profiles, start=1):
        lines: list[str] = [f"### Image {i}"]

        if p.attachment_role:
            lines.append(f"Role: {p.attachment_role}")

        if p.satellite_identity:
            si = p.satellite_identity
            parts = [x for x in [si.satellite, si.sensor] if x]
            if parts:
                lines.append("Platform: " + " / ".join(parts))
            if si.acquisition_date:
                lines.append(f"Acquired: {si.acquisition_date}")
            if si.tile:
                lines.append(f"Tile: {si.tile}")

        lines.append(f"Modality: {p.sensor_modality}")
        lines.append(f"Dimensions: {p.width} × {p.height} px, {p.band_count} band(s)")
        lines.append(
            f"Resolution: {p.resolution_x:g} × {p.resolution_y:g} {p.resolution_unit}"
        )
        lines.append(f"CRS: {p.crs.name} (EPSG:{p.crs.epsg or '?'})")

        bw = p.bounds_wgs84
        lines.append(
            f"Extent (WGS-84): {bw.west:.4f}°W–{bw.east:.4f}°E, "
            f"{bw.south:.4f}°N–{bw.north:.4f}°N"
        )
        lines.append(
            f"Center: {bw.center_lat:.4f}° N, {bw.center_lon:.4f}° E"
        )
        lines.append(f"Area: {p.geodesic_area.area_km2:.2f} km²")

        q = p.quality
        if q.valid_pixel_ratio is not None:
            lines.append(f"Valid pixels: {q.valid_pixel_ratio * 100:.1f}%")
        if q.cloud_cover_pct is not None:
            lines.append(f"Cloud cover: {q.cloud_cover_pct:.1f}%")

        if p.bands:
            band_labels = []
            for b in p.bands:
                label = b.polarization or b.designation or f"Band {b.band_index}"
                if b.stats and b.stats.mean is not None:
                    label += f" (mean={b.stats.mean:.2f})"
                band_labels.append(label)
            lines.append("Bands: " + ", ".join(band_labels))

        if p.total_rois > 0:
            lines.append(f"Detected regions of interest: {p.total_rois}")

        sections.append("\n".join(lines))

    aoi_contexts = aoi_contexts or []
    for aoi in aoi_contexts:
        lines = ["### AOI / Vector layer"]
        if aoi.attachment_role:
            lines.append(f"Role: {aoi.attachment_role}")
        lines.append(f"Features: {aoi.feature_count}")
        if aoi.crs_name:
            lines.append(f"CRS: {aoi.crs_name}")
        if aoi.wgs84_bounds:
            w, s, e, n = aoi.wgs84_bounds
            lines.append(f"Bounds: {w:.4f}°W–{e:.4f}°E, {s:.4f}°N–{n:.4f}°N")
        if aoi.total_area_km2 is not None:
            lines.append(f"Area: {aoi.total_area_km2:.2f} km²")
        sections.append("\n".join(lines))

    header = "You are analysing the following remote-sensing data:\n"
    context_block = "\n\n".join(sections)
    return f"{header}\n{context_block}\n\n### Query\n{user_query}"
