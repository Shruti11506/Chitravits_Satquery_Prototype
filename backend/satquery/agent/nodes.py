"""LangGraph node functions for the SatQuery agent.

Pipeline:  understand_query → preprocess → plan_tools → execute_tools
           → aggregate_results → response_generation

``plan_tools`` decides which tool(s) to run (or records why none applies).
``execute_tools`` dispatches to the selected tool(s) using bound clients.
``aggregate_results`` produces a structured AnalysisResult.
``response_generation`` assembles the final answer.
"""

from __future__ import annotations

import logging
import tempfile
import time

from satquery.agent.compatibility import check_compatibility as _check_compatibility
from satquery.agent.router import classify_task
from satquery.agent.state import (
    EARTHMIND_TASKS,
    AgentError,
    AgentState,
    EarthMindResult,
    TaskType,
    first_image_attachment,
)
from satquery.tools.aggregator import aggregate
from satquery.tools.compute.execute import run_operation
from satquery.tools.confidence import compute_confidence
from satquery.tools.operations import plan_operations
from satquery.tools.params import sanitize_params
from satquery.tools.registry import TOOL_REGISTRY
from satquery.tools.schemas import (
    AnalysisResult,
    Evidence,
    ExecutionPlan,
    Measurement,
    SpatialResult,
    ToolResult,
    ToolStatus,
)
from satquery.tools.selector import create_plan
from satquery.tools.workflows import plan_change_interpretation, plan_cross_modal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# understand_query — unchanged
# ---------------------------------------------------------------------------

async def understand_query(state: AgentState) -> dict:
    """Classify the task and pick the primary image attachment."""
    user_query = state["user_query"]
    task = classify_task(user_query)
    image_ref = first_image_attachment(user_query)
    logger.info("understand_query: task=%s image=%s", task.value, image_ref.id if image_ref else None)
    return {"task": task, "image_ref": image_ref}


# ---------------------------------------------------------------------------
# check_compatibility — validate inputs against the task before tool selection
# ---------------------------------------------------------------------------

async def check_compatibility(state: AgentState) -> dict:
    """Reject task/input mismatches before any tool runs; collect advisory warnings."""
    task: TaskType = state.get("task", TaskType.UNKNOWN)
    user_query = state["user_query"]
    report = _check_compatibility(task, user_query, state.get("data_profiles") or [])

    result: dict = {"compatibility_ok": report.ok}
    if report.warnings:
        result["warnings"] = list(report.warnings)
    if report.errors:
        logger.info("check_compatibility: blocked task=%s codes=%s",
                    task.value, [e.code for e in report.errors])
        result["errors"] = list(report.errors)
    return result


_COMPAT_BLOCKING = frozenset({
    "UNSUPPORTED_FORMAT", "INSUFFICIENT_IMAGES", "MODALITY_MISMATCH", "TEMPORAL_INCOMPATIBLE",
})


def route_after_compatibility(state: AgentState) -> str:
    """Skip planning/execution when the inputs are incompatible with the task."""
    if state.get("compatibility_ok", True):
        return "plan_tools"
    blocking = [e for e in (state.get("errors") or []) if e.code in _COMPAT_BLOCKING]
    return "build_evidence" if blocking else "plan_tools"


# ---------------------------------------------------------------------------
# plan_tools — replaces select_tool; uses ToolSelector
# ---------------------------------------------------------------------------

async def plan_tools(state: AgentState, *, available_tools: frozenset[str]) -> dict:
    """Create an ExecutionPlan, or record an error when no tool can satisfy the task."""
    task: TaskType = state.get("task", TaskType.UNKNOWN)
    image_ref = state.get("image_ref")
    data_profiles = state.get("data_profiles") or []
    aoi_contexts = state.get("aoi_contexts") or []
    user_query = state["user_query"]

    # Multi-tool workflows first (mentor requirements #6, #7):
    #   - cross-modal (optical + SAR) → parallel EarthMind calls, then aggregate
    #   - change interpretation → sequential MCD-Mamba → EarthMind
    plan: ExecutionPlan | None = None
    if task is TaskType.CROSS_MODAL_ANALYSIS:
        plan = plan_cross_modal(user_query, task.value, available_tools)
    elif task is TaskType.CHANGE_DETECTION:
        plan = plan_change_interpretation(user_query, task.value, available_tools)

    # Query-driven deterministic planning next: only the tools the specific query
    # needs (NDVI for vegetation, NDWI for water, SAR-Otsu for flood, …), never
    # "every index because the image is multispectral". An empty result defers to
    # the single-tool model selector (general VQA / grounding / general change).
    if plan is None:
        det_specs = plan_operations(
            state.get("query_text", ""), task.value, data_profiles, image_ref,
            available_tools,
        )
        if det_specs:
            reasoning = "query-driven deterministic plan: " + "; ".join(
                f"{s.tool_name} ({s.reason})" for s in det_specs
            )
            plan = ExecutionPlan(tools=det_specs, task=task.value, reasoning=reasoning)

    if plan is None:
        plan, error_code = create_plan(
            task=task.value,
            data_profiles=data_profiles,
            aoi_contexts=aoi_contexts,
            image_ref=image_ref,
            available_tools=available_tools,
        )
        if error_code:
            msg = {
                "NO_IMAGE": "This query needs a satellite image, but none was attached.",
                "UNSUPPORTED_TASK": _unsupported_message(task, available_tools),
            }.get(error_code, f"Cannot plan execution for task '{task.value}'.")
            return {
                "execution_plan": plan,
                "tool_selected": None,
                "errors": [AgentError(code=error_code, message=msg, stage="plan_tools")],
            }

    # Enforce the permitted-parameter schema (mentor requirement #4): drop any
    # param not in a tool's allow-list and record it as a warning.
    warnings = _enforce_param_schema(plan)

    tool_name = plan.tools[0].tool_name if plan.tools else None
    logger.info(
        "plan_tools: task=%s workflow=%s tools=%s",
        task.value, plan.workflow, [s.tool_name for s in plan.tools],
    )
    out: dict = {"execution_plan": plan, "tool_selected": tool_name}
    if warnings:
        out["warnings"] = warnings
    return out


def _enforce_param_schema(plan: ExecutionPlan) -> list[str]:
    """Sanitize every spec's params against the allow-list; return rejection warnings."""
    warnings: list[str] = []
    for spec in plan.tools:
        clean, rejected = sanitize_params(spec.tool_name, spec.params)
        if rejected:
            spec.params = clean
            warnings.append(
                f"Dropped non-permitted parameter(s) for '{spec.tool_name}': "
                f"{', '.join(rejected)}."
            )
    return warnings


def _unsupported_message(task: TaskType, available_tools: frozenset[str]) -> str:
    _msgs = {
        TaskType.CHANGE_DETECTION: (
            "Change detection requires the MCD-Mamba service, which is not available."
            if "mcd_mamba" not in available_tools
            else "Change detection failed to plan."
        ),
        TaskType.GROUNDING: (
            "Visual grounding requires the GeoGround service, which is not available."
            if "geoground" not in available_tools
            else "Visual grounding failed to plan."
        ),
        TaskType.MULTISPECTRAL_ANALYSIS: (
            "Multispectral / SAR analysis is not implemented yet."
        ),
    }
    return _msgs.get(task, f"Could not determine a supported task for query (task={task.value!r}).")


_BLOCKING_ERROR_CODES = frozenset({"NO_IMAGE", "UNSUPPORTED_TASK"})


def route_after_plan(state: AgentState) -> str:
    """Conditional edge: execute tools when the plan has tools and no blocking error.

    PREPROCESSING_FAILED is non-blocking — tools still run with degraded context.
    Only NO_IMAGE and UNSUPPORTED_TASK prevent tool execution.
    """
    plan = state.get("execution_plan")
    if not plan or not plan.tools:
        return "response_generation"
    blocking = [e for e in (state.get("errors") or []) if e.code in _BLOCKING_ERROR_CODES]
    if blocking:
        return "response_generation"
    return "execute_tools"


# ---------------------------------------------------------------------------
# execute_tools — dispatcher; returns tool_results list
# ---------------------------------------------------------------------------

def _call_kwargs(fn, candidates: dict) -> dict:
    """Keep only the keyword arguments ``fn`` actually accepts.

    The native in-tree clients and the remote wrapper adapters expose the same
    core ``infer`` signature, but the wrapper adapters additionally accept a SAR
    pair and a ground sample distance. Filtering here lets one handler drive
    both without branching on the client's type.
    """
    import inspect

    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins / C callables
        return dict(candidates)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(candidates)
    return {k: v for k, v in candidates.items() if k in params}


def _coregister_pair(before: bytes, after: bytes) -> tuple[bytes, bytes]:
    """Resample the AFTER image to the BEFORE image's pixel size when they differ.

    Change detection needs a co-registered, same-size bi-temporal pair; the
    input validator accepts captures that differ only in resolution or by a
    small, safely-normalisable aspect ratio, and this performs that
    normalisation before MCD-Mamba runs. It is a no-op when the two images are
    already the same size, and falls back to the originals (unchanged
    behaviour) for anything PIL cannot decode, such as a multi-band GeoTIFF.
    """
    try:
        import io

        from PIL import Image

        b = Image.open(io.BytesIO(before))
        b.load()
        a = Image.open(io.BytesIO(after))
        a.load()
        if a.size == b.size:
            return before, after
        resized = a.convert(b.mode) if a.mode != b.mode else a
        resized = resized.resize(b.size, Image.BILINEAR)
        buf = io.BytesIO()
        resized.save(buf, format="PNG")
        logger.info("MCD-Mamba: resampled after image %s -> %s to match before", a.size, b.size)
        return before, buf.getvalue()
    except Exception:  # noqa: BLE001 - normalisation is best-effort; never block inference
        logger.debug("MCD-Mamba: co-registration skipped (undecodable pair)", exc_info=True)
        return before, after


def _pixel_size_m(profile) -> float | None:
    """Ground sample distance in metres, when the raster records one.

    Returned only for metre-based CRSs: an area in hectares derived from degrees
    would be wrong, so it is left unreported instead.
    """
    if profile is None:
        return None
    if str(getattr(profile, "resolution_unit", "")).lower() not in {"meter", "meters", "metre", "metres", "m"}:
        return None
    res_x = getattr(profile, "resolution_x", None)
    res_y = getattr(profile, "resolution_y", None)
    sizes = [abs(float(r)) for r in (res_x, res_y) if isinstance(r, (int, float)) and r]
    if not sizes:
        return None
    return sum(sizes) / len(sizes)


def _change_evidence_brief(dep_name: str, dep_result: ToolResult) -> str:
    """Render an upstream change-detection result as evidence for interpretation.

    This is the hand-off in the two-step change pipeline: MCD-Mamba detects and
    quantifies, EarthMind reads that evidence and explains it. Only facts the
    detector actually reported are passed on — no invented magnitudes.
    """
    facts: list[str] = []
    if dep_result.answer:
        facts.append(dep_result.answer)
    for m in dep_result.measurements:
        facts.append(f"{m.name.replace('_', ' ')}: {m.value:g} {m.unit}")
    meta = dep_result.metadata or {}
    dims = meta.get("input_dimensions") or {}
    if dims.get("height") and dims.get("width"):
        facts.append(f"analysed at {dims['height']}x{dims['width']} px")
    if meta.get("sar_used"):
        facts.append("optical and SAR inputs were both used")
    if dep_result.spatial_results:
        facts.append(f"{len(dep_result.spatial_results)} distinct changed region(s) delineated")
    return f"[{dep_name} change evidence] " + "; ".join(facts)


def make_execute_tools_node(earthmind_client, resolver, mcd_mamba_client=None, geoground_client=None):
    """Factory: bind collaborators and return the async LangGraph node."""

    from satquery.agent.tools.attachment_resolver import AttachmentResolutionError
    from satquery.agent.tools.earthmind_client import EarthMindClient, EarthMindClientError
    from satquery.preprocessor.prompt_builder import build_vlm_context

    async def _run_earthmind(state: AgentState, spec, prior: dict) -> ToolResult:
        # Honour the spec's own attachment (parallel cross-modal runs one EarthMind
        # call per modality); fall back to the state's primary image.
        refs = {a.id: a for a in state["user_query"].attachments}
        image_ref = next((refs[i] for i in spec.attachment_ids if i in refs), None)
        if image_ref is None:
            image_ref = state.get("image_ref")
        if image_ref is None:
            return ToolResult(
                tool_name="earthmind",
                status=ToolStatus.FAILED,
                execution_time_ms=0,
                errors=["No image reference in state."],
            )

        try:
            resolved = await resolver.resolve(image_ref)
        except AttachmentResolutionError as exc:
            return ToolResult(
                tool_name="earthmind",
                status=ToolStatus.FAILED,
                execution_time_ms=0,
                errors=[f"{exc.code}: {exc.message}"],
                metadata={"error_code": exc.code},
            )

        vlm_query = build_vlm_context(
            state.get("data_profiles") or [],
            state["query_text"],
            state.get("aoi_contexts") or [],
        )

        # Sequential workflow: interpret an upstream tool's output (MCD-Mamba →
        # EarthMind). The dependency's measured change evidence is prepended so
        # EarthMind interprets a real detection rather than re-detecting it.
        upstream: list[str] = []
        for dep in spec.depends_on:
            dep_result = prior.get(dep)
            if dep_result is None:
                continue
            if dep_result.status is not ToolStatus.SUCCESS:
                # Never silently interpret a failed detection as if it succeeded.
                return ToolResult(
                    tool_name="earthmind",
                    status=ToolStatus.SKIPPED,
                    execution_time_ms=0,
                    errors=[
                        f"Skipped interpretation: upstream tool '{dep}' did not produce "
                        f"change evidence."
                    ],
                    metadata={"error_code": "UPSTREAM_FAILED", "depends_on": dep},
                )
            upstream.append(_change_evidence_brief(dep, dep_result))
        if upstream:
            vlm_query = (
                f"{' '.join(upstream)} Using only this evidence and the image, explain what "
                f"this change most likely represents on the ground and why. {vlm_query}"
            )

        try:
            from pathlib import Path
            from urllib.parse import urlparse
            suffix = Path(urlparse(image_ref.uri or "").path).suffix.lstrip(".").lower()
            fmt = suffix if suffix in {"png", "jpg", "jpeg", "webp", "bmp"} else None

            t0 = time.perf_counter()
            inference = await earthmind_client.infer(
                query=vlm_query,
                image_bytes=resolved.data,
                task=spec.task,
                image_format=fmt,
                metadata={"attachment_id": image_ref.id, "query_id": state.get("query_id", "")},
            )
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
        except EarthMindClientError as exc:
            return ToolResult(
                tool_name="earthmind",
                status=ToolStatus.FAILED,
                execution_time_ms=0,
                errors=[exc.message],
                metadata={"error_code": exc.code},
            )

        evidence = [Evidence(source_tool="earthmind", claim=inference.answer)]
        return ToolResult(
            tool_name="earthmind",
            status=ToolStatus.SUCCESS,
            execution_time_ms=inference.latency_ms or elapsed_ms,
            answer=inference.answer,
            evidence=evidence,
            metadata={
                "model": inference.model,
                "backend": inference.backend,
                "device": inference.device,
                "latency_ms": inference.latency_ms,
                "timings_ms": inference.timings_ms,
                "confidence": inference.confidence,
                "attachment_id": image_ref.id,
                "role": spec.reason or None,
            },
        )

    async def _run_mcd_mamba(state: AgentState, spec, prior: dict) -> ToolResult:
        if mcd_mamba_client is None:
            return ToolResult(
                tool_name="mcd_mamba",
                status=ToolStatus.FAILED,
                execution_time_ms=0,
                errors=["MCD-Mamba client not configured."],
                metadata={"error_code": "MAMBA_UNAVAILABLE"},
            )

        from satquery.agent.tools.mcd_mamba_client import MCDMambaClientError

        # Resolve before and after images.
        data_profiles = state.get("data_profiles") or []
        user_query = state["user_query"]
        attachments = {a.id: a for a in user_query.attachments}
        profiles_by_id = {p.attachment_id: p for p in data_profiles}

        def _by_role(role: str):
            return next(
                (attachments[p.attachment_id] for p in data_profiles
                 if p.attachment_role == role and p.attachment_id in attachments),
                None,
            )

        before_ref = _by_role("before")
        after_ref = _by_role("after")

        # If no temporal roles, fall back to first two images.
        image_refs = [a for a in user_query.attachments if a.kind.value == "image"]
        if before_ref is None and len(image_refs) >= 1:
            before_ref = image_refs[0]
        if after_ref is None and len(image_refs) >= 2:
            after_ref = image_refs[1]

        if before_ref is None:
            return ToolResult(
                tool_name="mcd_mamba",
                status=ToolStatus.FAILED,
                execution_time_ms=0,
                errors=["No images found for change detection."],
                metadata={"error_code": "NO_IMAGE"},
            )
        if after_ref is None or after_ref.id == before_ref.id:
            # The model compares two acquisitions; running it against one image
            # twice would report a fabricated "no change" result.
            return ToolResult(
                tool_name="mcd_mamba",
                status=ToolStatus.FAILED,
                execution_time_ms=0,
                errors=[
                    "Change detection needs two distinct images (a before and an after); "
                    "only one was available."
                ],
                metadata={"error_code": "INSUFFICIENT_IMAGES"},
            )

        # The model is multimodal: when a co-registered SAR pair is attached as
        # well, send it so the SAR branch contributes.
        sar_before_ref = sar_after_ref = None
        sar_images = [
            a for a in image_refs
            if a.modality is not None and a.modality.value == "sar"
            and a.id not in {before_ref.id, after_ref.id}
        ]
        for ref in sar_images:
            role = getattr(ref.role, "value", None)
            if role == "before" and sar_before_ref is None:
                sar_before_ref = ref
            elif role == "after" and sar_after_ref is None:
                sar_after_ref = ref
        if sar_before_ref is None and sar_after_ref is None and len(sar_images) >= 2:
            sar_before_ref, sar_after_ref = sar_images[0], sar_images[1]

        try:
            resolved_before = await resolver.resolve(before_ref)
            resolved_after = await resolver.resolve(after_ref)
            sar_before = await resolver.resolve(sar_before_ref) if sar_before_ref else None
            sar_after = await resolver.resolve(sar_after_ref) if sar_after_ref else None
        except AttachmentResolutionError as exc:
            return ToolResult(
                tool_name="mcd_mamba",
                status=ToolStatus.FAILED,
                execution_time_ms=0,
                errors=[f"{exc.code}: {exc.message}"],
                metadata={"error_code": exc.code},
            )

        # Safe normalisation: resample the pair to a common pixel grid so the
        # model receives co-registered, same-size bi-temporal inputs. The
        # change-detection validator accepts captures that differ only in
        # resolution or by a small (safely normalisable) aspect ratio; this is
        # the normalisation that relaxation assumes. Truly incompatible framings
        # are already rejected upstream, and this is a no-op for an identical
        # pair or for formats PIL cannot decode (e.g. a multi-band GeoTIFF).
        before_bytes, after_bytes = _coregister_pair(resolved_before.data, resolved_after.data)

        # Only pass a ground sample distance the preprocessor actually measured;
        # without it the adapter reports pixel counts and no hectare figure.
        pixel_size = _pixel_size_m(profiles_by_id.get(after_ref.id)) or _pixel_size_m(
            profiles_by_id.get(before_ref.id)
        )
        candidates = {
            "before_image_bytes": before_bytes,
            "after_image_bytes": after_bytes,
            "query": state["query_text"],
            "task": spec.task,
            "metadata": {"query_id": state.get("query_id", "")},
            "sar_before_bytes": sar_before.data if sar_before else None,
            "sar_after_bytes": sar_after.data if sar_after else None,
            "pixel_size_m": pixel_size,
            "patch_size": spec.params.get("patch_size"),
            "stride": spec.params.get("stride"),
        }
        kwargs = {
            k: v for k, v in _call_kwargs(mcd_mamba_client.infer, candidates).items()
            if v is not None or k in {"metadata"}
        }

        try:
            t0 = time.perf_counter()
            inference = await mcd_mamba_client.infer(**kwargs)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
        except MCDMambaClientError as exc:
            return ToolResult(
                tool_name="mcd_mamba",
                status=ToolStatus.FAILED,
                execution_time_ms=0,
                errors=[exc.message],
                metadata={"error_code": exc.code},
            )

        evidence = [Evidence(source_tool="mcd_mamba", claim=inference.summary)]
        measurements = []
        if inference.change_area_ha is not None:
            measurements.append(Measurement(
                name="change_area", value=inference.change_area_ha,
                unit="ha", source_tool="mcd_mamba",
            ))
        if inference.change_fraction is not None:
            measurements.append(Measurement(
                name="change_fraction", value=inference.change_fraction,
                unit="fraction", source_tool="mcd_mamba",
            ))

        spatial = [
            SpatialResult(
                region_id=r.get("region_id", f"region_{i}"),
                change_type=r.get("change_type"),
                area_ha=r.get("area_ha"),
                bbox=r.get("bbox"),
                confidence=r.get("confidence"),
                source_tool="mcd_mamba",
            )
            for i, r in enumerate(inference.change_regions or [])
        ]

        return ToolResult(
            tool_name="mcd_mamba",
            status=ToolStatus.SUCCESS,
            execution_time_ms=inference.latency_ms or elapsed_ms,
            answer=inference.summary,
            evidence=evidence,
            measurements=measurements,
            spatial_results=spatial,
            output_files=list(getattr(inference, "output_files", []) or []),
            metadata={
                "model": inference.model,
                "backend": inference.backend,
                "device": inference.device,
                "latency_ms": inference.latency_ms,
                "timings_ms": inference.timings_ms,
                "confidence": inference.confidence,
                "change_area_ha": inference.change_area_ha,
                "change_fraction": inference.change_fraction,
                "before_attachment_id": before_ref.id,
                "after_attachment_id": after_ref.id,
                **(inference.metadata or {}),
            },
        )

    async def _run_geoground(state: AgentState, spec, prior: dict) -> ToolResult:
        """Text-guided visual grounding through the real GeoGround service."""
        if geoground_client is None:
            return ToolResult(
                tool_name="geoground",
                status=ToolStatus.FAILED,
                execution_time_ms=0,
                errors=["GeoGround client not configured."],
                metadata={"error_code": "GEOGROUND_UNAVAILABLE"},
            )

        from satquery.agent.tools.geoground_client import GeoGroundClientError
        from satquery.tools.operations import extract_grounding_target

        refs = {a.id: a for a in state["user_query"].attachments}
        image_ref = next((refs[i] for i in spec.attachment_ids if i in refs), None) or state.get(
            "image_ref"
        )
        if image_ref is None:
            return ToolResult(
                tool_name="geoground", status=ToolStatus.FAILED, execution_time_ms=0,
                errors=["No image reference in state."], metadata={"error_code": "NO_IMAGE"},
            )

        # The target comes from the planner's permitted ``target`` parameter;
        # fall back to extracting it from the query text.
        target = spec.params.get("target") or extract_grounding_target(state.get("query_text", ""))
        if not target:
            return ToolResult(
                tool_name="geoground", status=ToolStatus.FAILED, execution_time_ms=0,
                errors=["Visual grounding needs a target to localize; none could be determined."],
                metadata={"error_code": "GEOGROUND_NO_TARGET"},
            )

        try:
            resolved = await resolver.resolve(image_ref)
        except AttachmentResolutionError as exc:
            return ToolResult(
                tool_name="geoground", status=ToolStatus.FAILED, execution_time_ms=0,
                errors=[f"{exc.code}: {exc.message}"], metadata={"error_code": exc.code},
            )

        from pathlib import Path
        from urllib.parse import urlparse
        hint = Path(urlparse(image_ref.uri or "").path).suffix or None

        try:
            t0 = time.perf_counter()
            inference = await geoground_client.infer(
                target=target,
                image_bytes=resolved.data,
                image_format=hint,
                max_points=spec.params.get("max_points"),
                generate_caption=spec.params.get("generate_caption"),
                metadata={"attachment_id": image_ref.id, "query_id": state.get("query_id", "")},
            )
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
        except GeoGroundClientError as exc:
            return ToolResult(
                tool_name="geoground", status=ToolStatus.FAILED, execution_time_ms=0,
                errors=[exc.message], metadata={"error_code": exc.code},
            )

        evidence = [Evidence(
            source_tool="geoground",
            claim=inference.summary,
            data={"target": inference.target, "geo_referenced": inference.geo_referenced},
        )]
        measurements = [Measurement(
            name="detection_count", value=float(len(inference.detections)),
            unit="count", source_tool="geoground",
        )]

        return ToolResult(
            tool_name="geoground",
            status=ToolStatus.SUCCESS,
            execution_time_ms=inference.latency_ms or elapsed_ms,
            answer=inference.caption or inference.summary,
            evidence=evidence,
            measurements=measurements,
            spatial_results=list(inference.detections),
            output_files=list(inference.output_files or []),
            metadata={
                "model": inference.model,
                "backend": inference.backend,
                "device": inference.device,
                "latency_ms": inference.latency_ms,
                "timings_ms": inference.timings_ms,
                "confidence": inference.confidence,
                "target": inference.target,
                "geo_referenced": inference.geo_referenced,
                "attachment_id": image_ref.id,
                **(inference.metadata or {}),
            },
        )

    _dispatch = {
        "earthmind": _run_earthmind,
        "mcd_mamba": _run_mcd_mamba,
        "geoground": _run_geoground,
    }

    async def execute_tools(state: AgentState) -> dict:
        plan = state.get("execution_plan")
        if not plan or not plan.tools:
            return {"tool_results": []}

        # Lookups + an output dir for derived GeoTIFFs (the scientific source of
        # truth; see spec §53). Created lazily only when a deterministic op runs.
        refs_by_id = {a.id: a for a in state["user_query"].attachments}
        profiles_by_id = {p.attachment_id: p for p in (state.get("data_profiles") or [])}
        out_dir_holder: dict[str, str] = {}

        def _out_dir() -> str:
            if "path" not in out_dir_holder:
                out_dir_holder["path"] = tempfile.mkdtemp(prefix="satquery_products_")
            return out_dir_holder["path"]

        # Respect declared execution order (sequential workflows set ascending
        # ``order``; ties are independent and could run concurrently). A dict of
        # completed results is threaded to each handler so a dependent spec (e.g.
        # EarthMind after MCD-Mamba) can consume upstream output.
        ordered = sorted(plan.tools, key=lambda s: s.order)
        results: list[ToolResult] = []
        completed: dict[str, ToolResult] = {}
        for spec in ordered:
            if spec.op_kind == "model":
                handler = _dispatch.get(spec.tool_name)
                if handler is None:
                    result = ToolResult(
                        tool_name=spec.tool_name, status=ToolStatus.FAILED,
                        execution_time_ms=0,
                        errors=[f"No handler for tool '{spec.tool_name}'."],
                    )
                else:
                    result = await handler(state, spec, completed)
            else:
                # Deterministic tool (spectral / sar / index_difference / grounding).
                result = await run_operation(
                    spec, resolver=resolver, refs_by_id=refs_by_id,
                    profiles_by_id=profiles_by_id, out_dir=_out_dir(),
                )
            results.append(result)
            completed.setdefault(spec.tool_name, result)

        # Surface tool errors into AgentErrors so response_generation can pick
        # them up. A SKIPPED step (a dependent tool whose upstream failed) is
        # reported too: a partial failure must never look like a clean run.
        new_errors: list[AgentError] = []
        for r in results:
            if r.status is ToolStatus.FAILED:
                code = r.metadata.get("error_code", f"{r.tool_name.upper()}_FAILED")
                msg = r.errors[0] if r.errors else f"{r.tool_name} failed."
                new_errors.append(AgentError(code=code, message=msg, stage="execute_tools"))
            elif r.status is ToolStatus.SKIPPED and r.errors:
                new_errors.append(AgentError(
                    code=r.metadata.get("error_code", f"{r.tool_name.upper()}_SKIPPED"),
                    message=r.errors[0],
                    stage="execute_tools",
                ))

        return {"tool_results": results, "errors": new_errors}

    return execute_tools


# ---------------------------------------------------------------------------
# aggregate_results — builds AnalysisResult and confidence score
# ---------------------------------------------------------------------------

async def aggregate_results(state: AgentState) -> dict:
    """Aggregate tool_results into a structured AnalysisResult."""
    tool_results = state.get("tool_results") or []
    if not tool_results:
        return {}

    result = aggregate(tool_results, state.get("query_text", ""))
    score = compute_confidence(tool_results, state.get("data_profiles") or [], result)
    result = result.model_copy(update={"confidence": score})
    return {"analysis_result": result, "confidence_score": score}


# ---------------------------------------------------------------------------
# response_generation — assembles final answer from AnalysisResult
# ---------------------------------------------------------------------------

async def response_generation(state: AgentState) -> dict:
    """Assemble the final answer (or leave it None when errors will be surfaced)."""
    analysis = state.get("analysis_result")

    if analysis is not None and analysis.tools_used:
        return {"final_answer": analysis.summary, "completed": True}

    # Legacy path: EarthMind result written directly (kept for any callers that bypass new nodes).
    result = state.get("earthmind_result")
    errors = state.get("errors") or []
    if result is not None and not errors:
        return {"final_answer": result.answer, "completed": True}

    return {"final_answer": None, "completed": False}
