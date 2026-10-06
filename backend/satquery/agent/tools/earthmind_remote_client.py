"""Adapter for the remote **EarthMind** wrapper API.

Contract (verified against the deployed service's OpenAPI document):

    GET  /health   -> {"status": "ok", "model": "...", "device": "..."}
    POST /predict  -> multipart/form-data
                        image: file   (PNG / JPEG / TIFF / ...)
                        query: str    (natural-language instruction)
                      -> {"status": "success", "query": "...", "prediction": "..."}

This adapter is drop-in compatible with :class:`satquery.agent.tools.
earthmind_client.EarthMindClient`: it exposes the same ``infer(...)`` keyword
signature and returns the same :class:`EarthMindInference` dataclass, so the
graph's ``_run_earthmind`` handler is unchanged.

The wrapper does not return a calibrated confidence, a device-level breakdown
or per-stage timings, so those fields stay ``None``/empty rather than being
invented. ``latency_ms`` is the measured round trip, labelled as such in
``timings_ms``.
"""

from __future__ import annotations

import logging
import time

from satquery.agent.tools.earthmind_client import EarthMindClientError, EarthMindInference
from satquery.agent.tools.wrapper_http import (
    WrapperApiError,
    WrapperClient,
    form_value,
    image_part,
)

logger = logging.getLogger(__name__)


class RemoteEarthMindClient(WrapperClient):
    """Calls the EarthMind wrapper's ``/predict`` endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 180.0,
        connect_timeout: float = 10.0,
        api_key: str | None = None,
        api_key_header: str = "Authorization",
        auth_scheme: str | None = "Bearer",
        health_path: str = "/health",
        predict_path: str = "/predict",
        model_name: str = "EarthMind-4B",
        client=None,
    ) -> None:
        super().__init__(
            service="EarthMind",
            code_prefix="EARTHMIND",
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
        self._model_name = model_name

    async def infer(
        self,
        *,
        query: str,
        image_bytes: bytes,
        task: str,
        image_format: str | None = None,
        metadata: dict | None = None,
    ) -> EarthMindInference:
        """Run single-image inference and return the parsed result.

        Raises :class:`EarthMindClientError` on every failure so callers see the
        same error type as the native-protocol client.
        """
        files = {"image": image_part(image_bytes, name="image", hint=image_format)}
        data = {"query": form_value(query)}

        t0 = time.perf_counter()
        try:
            body = await self.post_predict(files=files, data=data)
        except WrapperApiError as exc:
            raise EarthMindClientError(exc.code, exc.message) from None
        latency_ms = int((time.perf_counter() - t0) * 1000)

        prediction = body.get("prediction")
        if not isinstance(prediction, str) or not prediction.strip():
            raise EarthMindClientError(
                "EARTHMIND_BAD_RESPONSE",
                "The EarthMind API response did not contain a prediction.",
            )

        logger.info(
            "EarthMind inference ok (task=%s, chars=%d, latency=%dms)",
            task, len(prediction), latency_ms,
        )
        return EarthMindInference(
            task=task,
            answer=prediction.strip(),
            confidence=None,          # the wrapper exposes no calibrated score
            model=str(body.get("model") or self._model_name),
            device=body.get("device"),
            backend="wrapper_api",
            latency_ms=latency_ms,
            timings_ms={"round_trip": latency_ms},
        )
