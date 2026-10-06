"""Adapter for the remote **GeoGround** visual-grounding wrapper API.

Contract (verified against the deployed service's OpenAPI document):

    GET  /health   -> {"status": "ok", "model": "GeoGround", "device": "cuda", ...}
    POST /predict  -> multipart/form-data
                        image: file              (required; raster or GeoTIFF)
                        query: str               (required; target expression)
                        generate_caption: bool = false
                        max_points: int = 50     (polygon contour vertices)
                      -> {"status", "request_id", "model", "device",
                          "input": {image, query},
                          "output": {
                            "regions": [{label, bounding_box_pixel,
                                         bounding_box_geo, obb, ...}],
                            "bounding_boxes_pixel", "bounding_boxes_geo",
                            "oriented_bounding_boxes_pixel", ".._geo",
                            "masks", "coordinates_pixel", "coordinates_geo",
                            "confidence": [float], "evidence", "caption",
                            "output_image_file", "output_image_url",
                            "output_image_base64"},
                          "timestamp"}
    GET  /outputs/{filename}  -> the rendered grounding overlay

Geographic boxes are only present when the input carries a CRS (a GeoTIFF); for
a plain PNG the service returns pixel boxes and empty ``*_geo`` lists. The
adapter reports exactly that, rather than converting coordinates it cannot
justify.

There is no native-protocol equivalent of this service, so this adapter is the
only GeoGround client. ``satquery.tools.compute.grounding`` remains as a clearly
labelled mock for when GeoGround is not configured.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from satquery.agent.tools.wrapper_http import (
    WrapperApiError,
    WrapperClient,
    form_value,
    image_part,
)
from satquery.tools.schemas import OutputArtifact, SpatialResult

logger = logging.getLogger(__name__)


class GeoGroundClientError(Exception):
    """A structured, client-safe failure talking to the GeoGround service."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class GeoGroundInference:
    """Parsed successful response from the GeoGround wrapper."""

    summary: str
    target: str
    detections: list[SpatialResult] = field(default_factory=list)
    caption: str | None = None
    geo_referenced: bool = False
    confidence: float | None = None
    model: str = "GeoGround"
    device: str | None = None
    backend: str = "wrapper_api"
    latency_ms: int | None = None
    timings_ms: dict[str, int] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    output_files: list[OutputArtifact] = field(default_factory=list)


class GeoGroundClient(WrapperClient):
    """Calls the GeoGround wrapper's ``/predict`` endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 300.0,
        connect_timeout: float = 10.0,
        api_key: str | None = None,
        api_key_header: str = "Authorization",
        auth_scheme: str | None = "Bearer",
        health_path: str = "/health",
        predict_path: str = "/predict",
        max_points: int = 50,
        generate_caption: bool = False,
        include_base64: bool = False,
        model_name: str = "GeoGround",
        client=None,
    ) -> None:
        super().__init__(
            service="GeoGround",
            code_prefix="GEOGROUND",
            base_url=base_url,
            timeout=timeout,
            connect_timeout=connect_timeout,
            api_key=api_key,
            api_key_header=api_key_header,
            auth_scheme=auth_scheme,
            health_path=health_path,
            predict_path=predict_path,
            client=client,
        )
        self._max_points = max_points
        self._generate_caption = generate_caption
        self._include_base64 = include_base64
        self._model_name = model_name

    async def infer(
        self,
        *,
        target: str,
        image_bytes: bytes,
        image_format: str | None = None,
        max_points: int | None = None,
        generate_caption: bool | None = None,
        metadata: dict | None = None,
    ) -> GeoGroundInference:
        """Ground ``target`` in the image and return the detections."""
        if not target or not target.strip():
            raise GeoGroundClientError(
                "GEOGROUND_BAD_REQUEST",
                "Visual grounding needs a target expression (what to localize).",
            )

        files = {"image": image_part(image_bytes, name="image", hint=image_format)}
        caption = self._generate_caption if generate_caption is None else generate_caption
        data = {
            "query": form_value(target.strip()),
            "generate_caption": form_value(caption),
            "max_points": form_value(max_points or self._max_points),
        }

        t0 = time.perf_counter()
        try:
            body = await self.post_predict(files=files, data=data)
        except WrapperApiError as exc:
            raise GeoGroundClientError(exc.code, exc.message) from None
        latency_ms = int((time.perf_counter() - t0) * 1000)

        out = body.get("output")
        if not isinstance(out, dict):
            raise GeoGroundClientError(
                "GEOGROUND_BAD_RESPONSE",
                "The GeoGround API response did not contain an output section.",
            )

        detections, geo_referenced = self._parse_detections(out, target.strip())
        scores = [s for s in (out.get("confidence") or []) if isinstance(s, (int, float))]
        # A single positive score is the model's own mask score; keep it, but do
        # not synthesise one when the model reported none (or reported 0.0).
        top_confidence = max(scores) if scores and max(scores) > 0 else None

        outputs = []
        url = self.output_url(out.get("output_image_url") or out.get("output_image_file"))
        if url:
            outputs.append(OutputArtifact(
                name=str(out.get("output_image_file") or "grounding_overlay.png"),
                kind="overlay",
                url=url,
                media_type="image/png",
                producer="geoground",
                data_base64=out.get("output_image_base64") if self._include_base64 else None,
            ))

        summary = self._summarize(target.strip(), detections, geo_referenced)
        caption_text = out.get("caption") if isinstance(out.get("caption"), str) else None

        logger.info(
            "GeoGround inference ok (target=%r, detections=%d, geo=%s, latency=%dms)",
            target, len(detections), geo_referenced, latency_ms,
        )
        return GeoGroundInference(
            summary=summary,
            target=target.strip(),
            detections=detections,
            caption=caption_text,
            geo_referenced=geo_referenced,
            confidence=top_confidence,
            model=str(body.get("model") or self._model_name),
            device=body.get("device"),
            latency_ms=latency_ms,
            timings_ms={"round_trip": latency_ms},
            metadata={
                "request_id": body.get("request_id"),
                "mask_count": len(out.get("masks") or []),
                "confidence_scores": scores,
                "geo_referenced": geo_referenced,
                "max_points": int(data["max_points"]),
                "model_evidence": out.get("evidence"),
                "timestamp": body.get("timestamp"),
            },
            output_files=outputs,
        )

    # --- response parsing --------------------------------------------------

    @staticmethod
    def _parse_detections(out: dict, target: str) -> tuple[list[SpatialResult], bool]:
        """Turn the wrapper's region list into ``SpatialResult`` detections.

        Returns ``(detections, geo_referenced)``. ``geo_referenced`` is True only
        when the service actually resolved geographic coordinates, which requires
        the input raster to carry a CRS.
        """
        regions = out.get("regions")
        scores = [s for s in (out.get("confidence") or []) if isinstance(s, (int, float))]
        detections: list[SpatialResult] = []
        geo_any = False

        if not isinstance(regions, list) or not regions:
            # Fall back to the flat pixel-box list when no structured regions came back.
            for i, box in enumerate(out.get("bounding_boxes_pixel") or []):
                if not (isinstance(box, list) and len(box) == 4):
                    continue
                detections.append(SpatialResult(
                    region_id=f"{target}_{i}",
                    bbox=[float(v) for v in box],
                    confidence=scores[i] if i < len(scores) and scores[i] > 0 else None,
                    source_tool="geoground",
                ))
            return detections, False

        for i, region in enumerate(regions):
            if not isinstance(region, dict):
                continue
            pixel_box = region.get("bounding_box_pixel")
            geo_box = region.get("bounding_box_geo")
            bbox = (
                [float(v) for v in pixel_box]
                if isinstance(pixel_box, list) and len(pixel_box) == 4
                else None
            )
            if isinstance(geo_box, dict) and geo_box:
                geo_any = True
            detections.append(SpatialResult(
                region_id=f"{region.get('label') or target}_{i}",
                bbox=bbox,
                confidence=scores[i] if i < len(scores) and scores[i] > 0 else None,
                source_tool="geoground",
            ))
        return detections, geo_any

    @staticmethod
    def _summarize(target: str, detections: list[SpatialResult], geo: bool) -> str:
        if not detections:
            return f"GeoGround did not localize any region matching '{target}' in this image."
        where = "with geographic coordinates" if geo else "in pixel coordinates only (no CRS in the input)"
        plural = "region" if len(detections) == 1 else "regions"
        return (
            f"GeoGround localized {len(detections)} {plural} matching '{target}', {where}."
        )
