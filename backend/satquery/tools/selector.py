"""Tool selector: picks the right tool(s) based on task, data profiles, and signal.

This is NOT keyword-only routing -- decisions are informed by:
  - TaskType (primary signal)
  - DataProfile list: sensor modality, temporal roles, image count
  - AOIContext list: whether spatial grounding is available
  - available_tools: which clients are actually wired up
"""

from __future__ import annotations

from satquery.tools.registry import TOOL_REGISTRY, tool_for_task
from satquery.tools.schemas import ExecutionPlan, ToolSpec


def _has_temporal_pair(attachment_ids_with_roles: list[tuple[str, str | None]]) -> bool:
    roles = {r for _, r in attachment_ids_with_roles if r}
    return "before" in roles and "after" in roles


def create_plan(
    task: str,
    data_profiles: list,    # list[DataProfile] — imported lazily to avoid circular
    aoi_contexts: list,     # list[AOIContext]
    image_ref,              # AttachmentRef | None — the primary image for the query
    available_tools: frozenset[str],
) -> tuple[ExecutionPlan, str | None]:
    """Return (ExecutionPlan, error_code_or_None).

    ``error_code`` is set when no tool can satisfy the request.
    """
    cap = None
    selected = tool_for_task(task, available_tools)

    if selected is None:
        return ExecutionPlan(task=task, reasoning="No tool registered for this task."), "UNSUPPORTED_TASK"

    cap = TOOL_REGISTRY[selected]

    # Check image requirement.
    if cap.requires_image and image_ref is None:
        return ExecutionPlan(task=task, reasoning="Image required but none attached."), "NO_IMAGE"

    # Check temporal pair requirement (before + after).
    id_role_pairs = [(p.attachment_id, p.attachment_role) for p in data_profiles]
    if cap.requires_temporal_pair and not _has_temporal_pair(id_role_pairs):
        # Fall back: if we have any image, still try (the model will do its best).
        # Only hard-fail if no image at all.
        if image_ref is None:
            return ExecutionPlan(
                task=task,
                reasoning="Change detection requires before+after images but none found.",
            ), "NO_IMAGE"

    # Build attachment list for this tool.
    if cap.requires_temporal_pair:
        attachment_ids = [
            p.attachment_id for p in data_profiles
            if p.attachment_role in ("before", "after")
        ]
        # Fall back to all profiles if roles not labelled.
        if not attachment_ids:
            attachment_ids = [p.attachment_id for p in data_profiles]
        if not attachment_ids and image_ref:
            attachment_ids = [image_ref.id]
    else:
        attachment_ids = [image_ref.id] if image_ref else []

    spec = ToolSpec(
        tool_name=selected,
        task=task,
        attachment_ids=attachment_ids,
        primary=True,
    )

    reasoning = f"Task '{task}' → tool '{selected}'"
    if cap.requires_temporal_pair:
        reasoning += f" (temporal pair: {attachment_ids})"

    return ExecutionPlan(tools=[spec], task=task, reasoning=reasoning), None
