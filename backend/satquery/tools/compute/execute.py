"""Execute a deterministic ``ToolSpec`` by resolving its images and running it.

Bridges the agent's async attachment resolution to the synchronous tool
runners. Given a ToolSpec with an ``op_kind`` of spectral/sar/index_difference/
grounding, it resolves the referenced attachment(s) to bytes and dispatches to
the matching runner, returning a ``ToolResult``. Resolution failures become a
failed ToolResult (never an exception that would crash the graph).
"""

from __future__ import annotations

from satquery.tools.compute.grounding import run_grounding
from satquery.tools.compute.runner import run_index_difference, run_sar, run_spectral
from satquery.tools.schemas import ToolResult, ToolSpec, ToolStatus


def _fail(name: str, message: str, code: str = "RESOLVE_FAILED") -> ToolResult:
    return ToolResult(tool_name=name, status=ToolStatus.FAILED, execution_time_ms=0,
                      errors=[message], metadata={"error_code": code})


async def run_operation(
    spec: ToolSpec, *, resolver, refs_by_id: dict, profiles_by_id: dict,
    out_dir=None,
) -> ToolResult:
    """Resolve images for ``spec`` and run the corresponding deterministic tool."""
    from satquery.agent.tools.attachment_resolver import AttachmentResolutionError

    async def _bytes(att_id: str):
        ref = refs_by_id.get(att_id)
        if ref is None:
            raise AttachmentResolutionError("NO_REF", f"no attachment for id '{att_id}'")
        resolved = await resolver.resolve(ref)
        return resolved.data

    try:
        if spec.op_kind == "index_difference":
            before_id = spec.params["before"]
            after_id = spec.params["after"]
            before = await _bytes(before_id)
            after = await _bytes(after_id)
            return run_index_difference(
                spec.params["index"], before, after,
                profiles_by_id.get(before_id), profiles_by_id.get(after_id),
                out_dir=out_dir,
            )

        att_id = spec.attachment_ids[0]
        data = await _bytes(att_id)
        profile = profiles_by_id.get(att_id)

        if spec.op_kind == "spectral":
            return run_spectral(spec.tool_name, data, profile, out_dir=out_dir)
        if spec.op_kind == "sar":
            return run_sar(spec.tool_name, data, profile,
                           band=spec.params.get("band", "VV"), out_dir=out_dir)
        if spec.op_kind == "grounding":
            return run_grounding(data, profile, label=spec.params.get("label", "object"))
        return _fail(spec.tool_name, f"unknown op_kind '{spec.op_kind}'", "UNKNOWN_OP")
    except AttachmentResolutionError as exc:
        return _fail(spec.tool_name, f"{exc.code}: {exc.message}", exc.code)
    except Exception as exc:  # noqa: BLE001
        return _fail(spec.tool_name, f"{spec.tool_name} failed: {exc}")
