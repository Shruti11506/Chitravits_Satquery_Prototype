"""The EarthMind tool: the graph node that turns an image + question into a result.

It owns the sequence the spec calls for -- read state, resolve the image, prepare
and send the request, handle every failure mode, parse the structured response,
and write it back into ``AgentState`` -- while exposing none of the HTTP or
storage detail to the rest of the graph. Transport lives in
``EarthMindClient``; byte-fetching lives in ``AttachmentResolver``.

``make_earthmind_tool`` binds those collaborators and returns the async node.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

from satquery.agent.state import AgentError, AgentState, EarthMindResult, TaskType
from satquery.agent.tools.attachment_resolver import AttachmentResolutionError, AttachmentResolver
from satquery.agent.tools.earthmind_client import EarthMindClient, EarthMindClientError
from satquery.input.schemas import AttachmentRef
from satquery.preprocessor.prompt_builder import build_vlm_context

logger = logging.getLogger(__name__)

_STAGE = "earthmind_tool"
# Extensions the RGB tasks accept; hints the service, which does the real validation.
_RGB_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp"}


def make_earthmind_tool(client: EarthMindClient, resolver: AttachmentResolver):
    """Bind the tool's collaborators and return the LangGraph node coroutine."""

    async def earthmind_tool(state: AgentState) -> dict:
        task: TaskType = state.get("task", TaskType.UNKNOWN)
        image_ref: AttachmentRef | None = state.get("image_ref")

        if image_ref is None:
            return _error("NO_IMAGE", "This task needs a satellite image, but none was provided.")

        # 1. Resolve the reference to bytes.
        try:
            resolved = await resolver.resolve(image_ref)
        except AttachmentResolutionError as exc:
            logger.info("Attachment resolution failed [%s]: %s", exc.code, exc.message)
            return _error(exc.code, exc.message)

        # 2. Prepare + send the request.
        try:
            vlm_query = build_vlm_context(
                state.get("data_profiles") or [],
                state["query_text"],
                state.get("aoi_contexts") or [],
            )
            inference = await client.infer(
                query=vlm_query,
                image_bytes=resolved.data,
                task=task.value,
                image_format=_format_hint(image_ref),
                metadata={"attachment_id": image_ref.id, "query_id": state.get("query_id", "")},
            )
        except EarthMindClientError as exc:
            logger.info("EarthMind call failed [%s]: %s", exc.code, exc.message)
            return _error(exc.code, exc.message)

        # 3. Parse into structured state.
        result = EarthMindResult(
            task=inference.task or task.value,
            answer=inference.answer,
            confidence=inference.confidence,
            model=inference.model,
            device=inference.device,
            backend=inference.backend,
            latency_ms=inference.latency_ms,
            timings_ms=inference.timings_ms,
        )
        return {
            "earthmind_result": result,
            "confidence": inference.confidence,
            "latency_ms": inference.latency_ms,
            "timings_ms": inference.timings_ms,
            "tool_selected": "earthmind",
        }

    return earthmind_tool


def _error(code: str, message: str) -> dict:
    return {"errors": [AgentError(code=code, message=message, stage=_STAGE)]}


def _format_hint(attachment: AttachmentRef) -> str | None:
    """Best-effort file-format hint from the uri extension (advisory only)."""
    if not attachment.uri:
        return None
    suffix = Path(urlparse(attachment.uri).path).suffix.lstrip(".").lower()
    return suffix if suffix in _RGB_EXTENSIONS else None
