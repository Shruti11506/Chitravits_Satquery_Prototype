"""Adapter for the remote **MCD-Mamba** change-detection wrapper API.

Contract (verified against the deployed service's OpenAPI document):

    GET  /health   -> {"status": "ok", "model": "MCD-Mamba",
                       "architecture": "STMambaBCD_multimodal", "device": "cuda",
                       "optical_bands": 13, "sar_bands": 2}
    POST /predict  -> multipart/form-data
                        opt_pre:  file          (required, pre-change optical)
                        opt_post: file          (required, post-change optical)
                        sar_pre:  file          (optional, pre-change SAR)
                        sar_post: file          (optional, post-change SAR)
                        patch_size: int = 224
                        stride: int | None
                        return_probabilities: bool = false
                      -> {"status", "request_id", "model", "device",
                          "input_dimensions": {height, width, optical_bands, sar_bands},
                          "change_detected", "change_pixel_count", "total_pixels",
                          "change_ratio", "output_file", "change_map_url",
                          "change_map_base64", "probability_stats"}
    GET  /outputs/{filename}  -> the rendered change map

Drop-in compatible with :class:`satquery.agent.tools.mcd_mamba_client.
MCDMambaClient`: same ``infer(...)`` signature, same
:class:`MCDMambaInference` return type.

Two deliberate omissions, so nothing is fabricated:

* **No confidence.** ``probability_stats`` is the distribution of per-pixel
  change logits, not a calibrated detection confidence. It is carried through
  as metadata and never presented as ``confidence``.
* **No area in hectares** unless a ground sample distance is supplied. The
  wrapper reports pixel counts only; ``pixel_size_m`` lets the caller pass the
  real resolution from the preprocessor's ``DataProfile``, and the area is
  computed from it. Without it, ``change_area_ha`` stays ``None``.
"""

from __future__ import annotations

import logging
import time

from satquery.agent.tools.mcd_mamba_client import MCDMambaClientError, MCDMambaInference
from satquery.agent.tools.wrapper_http import (
    WrapperApiError,
    WrapperClient,
    form_value,
    image_part,
)
from satquery.tools.schemas import OutputArtifact

logger = logging.getLogger(__name__)


class RemoteMCDMambaClient(WrapperClient):
    """Calls the MCD-Mamba wrapper's ``/predict`` endpoint."""

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
        patch_size: int = 224,
        return_probabilities: bool = True,
        include_base64: bool = False,
        model_name: str = "MCD-Mamba",
        client=None,
    ) -> None:
        super().__init__(
            service="MCD-Mamba",
            code_prefix="MAMBA",
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
        self._patch_size = patch_size
        self._return_probabilities = return_probabilities
        self._include_base64 = include_base64
        self._model_name = model_name

    async def infer(
        self,
        before_image_bytes: bytes,
        after_image_bytes: bytes,
        query: str = "",
        task: str = "change_detection",
        image_format: str | None = None,
        metadata: dict | None = None,
        *,
        sar_before_bytes: bytes | None = None,
        sar_after_bytes: bytes | None = None,
        patch_size: int | None = None,
        stride: int | None = None,
        pixel_size_m: float | None = None,
    ) -> MCDMambaInference:
        """Run bi-temporal change detection on an optical (optionally +SAR) pair."""
        files = {
            "opt_pre": image_part(before_image_bytes, name="opt_pre", hint=image_format),
            "opt_post": image_part(after_image_bytes, name="opt_post", hint=image_format),
        }
        # The model is STMambaBCD_multimodal: when a co-registered SAR pair is
        # attached, send it so the SAR branch actually contributes.
        if sar_before_bytes and sar_after_bytes:
            files["sar_pre"] = image_part(sar_before_bytes, name="sar_pre")
            files["sar_post"] = image_part(sar_after_bytes, name="sar_post")

        data = {
            "patch_size": form_value(patch_size or self._patch_size),
            "return_probabilities": form_value(self._return_probabilities),
        }
        if stride is not None:
            data["stride"] = form_value(stride)

        t0 = time.perf_counter()
        try:
            body = await self.post_predict(files=files, data=data)
        except WrapperApiError as exc:
            raise MCDMambaClientError(exc.code, exc.message) from None
        latency_ms = int((time.perf_counter() - t0) * 1000)

        changed_px = body.get("change_pixel_count")
        total_px = body.get("total_pixels")
        ratio = body.get("change_ratio")
        if not isinstance(changed_px, (int, float)) or not isinstance(total_px, (int, float)):
            raise MCDMambaClientError(
                "MAMBA_BAD_RESPONSE",
                "The MCD-Mamba API response did not contain change pixel statistics.",
            )
        if not isinstance(ratio, (int, float)):
            ratio = (float(changed_px) / float(total_px)) if total_px else None

        dims = body.get("input_dimensions") or {}
        change_detected = bool(body.get("change_detected", bool(changed_px)))

        # Area is only reported when a real ground sample distance is known.
        area_ha = None
        if pixel_size_m and pixel_size_m > 0:
            area_ha = round(float(changed_px) * (float(pixel_size_m) ** 2) / 10_000.0, 4)

        summary = self._summarize(
            change_detected=change_detected,
            changed_px=int(changed_px),
            total_px=int(total_px),
            ratio=ratio,
            area_ha=area_ha,
            multimodal="sar_pre" in files,
        )

        outputs = []
        url = self.output_url(body.get("change_map_url") or body.get("output_file"))
        if url:
            outputs.append(OutputArtifact(
                name=str(body.get("output_file") or "change_map.png"),
                kind="change_map",
                url=url,
                media_type="image/png",
                producer="mcd_mamba",
                data_base64=body.get("change_map_base64") if self._include_base64 else None,
            ))

        meta = {
            "request_id": body.get("request_id"),
            "architecture": body.get("architecture"),
            "change_detected": change_detected,
            "change_pixel_count": int(changed_px),
            "total_pixels": int(total_px),
            "input_dimensions": dims,
            "probability_stats": body.get("probability_stats"),
            "patch_size": int(data["patch_size"]),
            "sar_used": "sar_pre" in files,
            "pixel_size_m": pixel_size_m,
        }
        if stride is not None:
            meta["stride"] = stride

        logger.info(
            "MCD-Mamba inference ok (changed=%s, ratio=%s, latency=%dms)",
            change_detected, ratio, latency_ms,
        )
        return MCDMambaInference(
            summary=summary,
            change_regions=[],        # the wrapper returns a raster map, not vector regions
            change_area_ha=area_ha,
            change_fraction=round(float(ratio), 6) if ratio is not None else None,
            confidence=None,          # probability_stats is not a calibrated confidence
            model=str(body.get("model") or self._model_name),
            device=body.get("device"),
            backend="wrapper_api",
            latency_ms=latency_ms,
            timings_ms={"round_trip": latency_ms},
            metadata=meta,
            output_files=outputs,
        )

    @staticmethod
    def _summarize(
        *,
        change_detected: bool,
        changed_px: int,
        total_px: int,
        ratio: float | None,
        area_ha: float | None,
        multimodal: bool,
    ) -> str:
        """State exactly what the model measured — no interpretation."""
        sensors = "optical + SAR" if multimodal else "optical"
        if not change_detected or changed_px == 0:
            return (
                f"No change was detected between the two {sensors} acquisitions "
                f"across {total_px:,} analysed pixels."
            )
        pct = f"{ratio * 100:.1f}%" if ratio is not None else "an unreported share"
        area = f" (~{area_ha:g} ha)" if area_ha is not None else ""
        return (
            f"Change detected over {changed_px:,} of {total_px:,} pixels, "
            f"{pct} of the analysed {sensors} scene{area}."
        )
