"""Multi-tool workflow planners: parallel (cross-modal) and sequential (change).

These build ``ExecutionPlan``s that the single-tool ``selector.create_plan`` does
not: an optical + SAR pair analysed in parallel then aggregated, and a
MCD-Mamba → EarthMind sequence where EarthMind interprets the detected change.

Both return ``None`` when they do not apply, so ``plan_tools`` can fall through
to the deterministic operation planner or the single-tool selector.
"""

from __future__ import annotations

import re

from satquery.input.schemas import UserQuery
from satquery.tools.schemas import ExecutionPlan, ToolSpec

_OPTICAL_LIKE = frozenset({"optical", "multispectral", "hyperspectral"})

# Cues that the user wants the change *interpreted*, not just detected/measured.
_INTERPRET_CUES = re.compile(
    r"\b(interpret|explain|why|describe|what (kind|type)|characteri[sz]e|"
    r"what happened|significance|assess|summar)\w*\b",
    re.IGNORECASE,
)


def _images(user_query: UserQuery) -> list:
    return [a for a in user_query.attachments if a.kind.value == "image"]


def _pick_by_modality(images: list, modalities: frozenset[str]):
    return next((a for a in images if a.modality is not None and a.modality.value in modalities), None)


def plan_cross_modal(
    user_query: UserQuery,
    task: str,
    available_tools: frozenset[str],
) -> ExecutionPlan | None:
    """Parallel optical + SAR analysis via EarthMind, aggregated downstream.

    Two independent EarthMind calls (order 0, no dependencies) — one per modality
    — so the executor may run them concurrently and the aggregator merges them.
    """
    if "earthmind" not in available_tools:
        return None
    images = _images(user_query)
    optical = _pick_by_modality(images, _OPTICAL_LIKE)
    sar = _pick_by_modality(images, frozenset({"sar"}))
    if optical is None or sar is None:
        return None

    specs = [
        ToolSpec(
            tool_name="earthmind", task=task, attachment_ids=[optical.id],
            primary=True, op_kind="model", order=0,
            params={}, reason="optical scene analysis (cross-modal)",
        ),
        ToolSpec(
            tool_name="earthmind", task=task, attachment_ids=[sar.id],
            primary=True, op_kind="model", order=0,
            params={}, reason="SAR scene analysis (cross-modal)",
        ),
    ]
    return ExecutionPlan(
        tools=specs,
        task=task,
        workflow="parallel",
        reasoning=(
            f"Cross-modal analysis → parallel EarthMind on optical '{optical.id}' and "
            f"SAR '{sar.id}'; results aggregated independently."
        ),
    )


def plan_change_interpretation(
    user_query: UserQuery,
    task: str,
    available_tools: frozenset[str],
) -> ExecutionPlan | None:
    """Sequential MCD-Mamba → EarthMind so EarthMind interprets the detected change.

    Applies only when both tools are available and the query asks for an
    interpretation of the change (not just its area/fraction). EarthMind (order 1)
    depends on MCD-Mamba (order 0); the executor feeds the change summary into the
    EarthMind prompt.
    """
    if "mcd_mamba" not in available_tools or "earthmind" not in available_tools:
        return None
    if not _INTERPRET_CUES.search(user_query.query or ""):
        return None

    images = _images(user_query)
    before = next((a for a in images if a.role is not None and a.role.value == "before"), None)
    after = next((a for a in images if a.role is not None and a.role.value == "after"), None)
    if before is None and len(images) >= 1:
        before = images[0]
    if after is None and len(images) >= 2:
        after = images[1]
    if before is None:
        return None

    interpret_target = after or before
    specs = [
        ToolSpec(
            tool_name="mcd_mamba", task=task,
            attachment_ids=[a.id for a in (before, after) if a is not None],
            primary=True, op_kind="model", order=0,
            reason="detect and quantify bi-temporal change",
        ),
        ToolSpec(
            tool_name="earthmind", task=task, attachment_ids=[interpret_target.id],
            primary=False, op_kind="model", order=1, depends_on=["mcd_mamba"],
            reason="interpret the detected change on the after scene",
        ),
    ]
    return ExecutionPlan(
        tools=specs,
        task=task,
        workflow="sequential",
        reasoning=(
            "Change interpretation → MCD-Mamba detects the change, then EarthMind "
            "interprets it (sequential; EarthMind consumes MCD-Mamba's summary)."
        ),
    )
