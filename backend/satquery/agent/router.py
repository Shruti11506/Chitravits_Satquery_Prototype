"""Query router / planner: classify a natural-language query into a ``TaskType``.

This is a deliberately small, transparent, rule-based classifier -- a correct
baseline, not a premature ML step. It recognises the two capabilities that
currently route to EarthMind (VQA and general visual analysis) and *names* the
future capabilities (change detection, grounding, multispectral) so the agent
can return an honest "not implemented" instead of misrouting them.

The seam is intentional: swapping in an LLM-based planner later means replacing
``classify_task`` alone.
"""

from __future__ import annotations

import re

from satquery.agent.state import TaskType
from satquery.input.schemas import UserQuery

# Keyword cues. Order matters: more specific (unsupported) tasks are checked first
# so we do not misclassify "what changed between these images" as generic VQA.
_CHANGE_CUES = re.compile(
    r"\b(change|changed|difference|differ|before and after|deforestation|"
    r"encroach\w*|new construction|expansion)\b",
    re.IGNORECASE,
)
# Grounding / detection is a *spatial action*: the user wants something found,
# localised, outlined, or returned as boxes -- not described or counted. These
# route to GeoGround. A question that merely names an object ("how many
# airplanes?", "are there airplanes?", "describe the airplanes") is VQA, not
# grounding, and must fall through to the VQA branch -> EarthMind. Kept in step
# with ``tools.operations._GROUNDING`` so classification and planning agree.
_GROUNDING_CUES = re.compile(
    r"\b("
    r"where (is|are)|locate|locali[sz]\w*|pinpoint|highlight|delineate|"
    r"outline the|mark the|segment the|segment all|show me where|"
    r"identify (the )?location|bounding box(es)?|"
    r"detect (the|all|every)|object detection|return bounding box|find (the|all)"
    r")\b",
    re.IGNORECASE,
)
_MULTISPECTRAL_CUES = re.compile(
    r"\b(ndvi|multispectral|hyperspectral|sar|band \d|near.?infrared|nir|radar backscatter)\b",
    re.IGNORECASE,
)
_CROSS_MODAL_CUES = re.compile(
    r"\b(cross.?modal|optical and sar|sar and optical|optical\s*[+/&]\s*sar|"
    r"sar\s*[+/&]\s*optical|combine .*(optical|sar)|fuse .*(optical|sar)|"
    r"compare .*optical .*sar|radar and optical)\b",
    re.IGNORECASE,
)
_ANALYSIS_CUES = re.compile(
    r"\b(describe|description|analy[sz]e|analysis|summar\w+|what do you see|"
    r"overview|assess|interpret|caption)\b",
    re.IGNORECASE,
)


def classify_task(user_query: UserQuery) -> TaskType:
    """Map a query to a task type using its text and (lightly) its attachments."""
    text = user_query.query

    # Explicit override via metadata wins (lets callers force a task).
    forced = user_query.metadata.get("task")
    if isinstance(forced, str):
        try:
            return TaskType(forced.strip().lower())
        except ValueError:
            pass

    # Optical + SAR joint analysis: both modalities attached, or the query asks to
    # combine/compare them. Checked before the single-modality branches so a mixed
    # pair is not mislabelled as generic multispectral or change.
    if _is_cross_modal(user_query) or _CROSS_MODAL_CUES.search(text):
        return TaskType.CROSS_MODAL_ANALYSIS
    # Multi-image temporal comparisons and multispectral modalities are known but
    # unimplemented; classify them honestly so the agent can say so.
    if _has_multispectral_attachment(user_query) or _MULTISPECTRAL_CUES.search(text):
        return TaskType.MULTISPECTRAL_ANALYSIS
    if _CHANGE_CUES.search(text) or _has_temporal_pair(user_query):
        return TaskType.CHANGE_DETECTION
    if _GROUNDING_CUES.search(text):
        return TaskType.GROUNDING
    if _ANALYSIS_CUES.search(text):
        return TaskType.VISUAL_ANALYSIS
    # A question mark or interrogative with an image is VQA; a bare "analyse this" fell
    # through above. Default questions about an image to VQA.
    if "?" in text or _looks_like_question(text):
        return TaskType.VQA
    # No strong cue: if there is an image, treat it as visual analysis; otherwise unknown.
    return TaskType.VISUAL_ANALYSIS if user_query.attachments else TaskType.UNKNOWN


def _looks_like_question(text: str) -> bool:
    return bool(re.match(r"\s*(what|which|where|how many|is there|are there|can you|do you)\b",
                         text, re.IGNORECASE))


def _has_multispectral_attachment(user_query: UserQuery) -> bool:
    return any(
        a.modality is not None and a.modality.value in {"multispectral", "hyperspectral", "sar"}
        for a in user_query.attachments
    )


def _has_temporal_pair(user_query: UserQuery) -> bool:
    roles = {a.role.value for a in user_query.attachments if a.role is not None}
    return {"before", "after"} <= roles


def _is_cross_modal(user_query: UserQuery) -> bool:
    """True when both an optical-family image and a SAR image are attached."""
    mods = {a.modality.value for a in user_query.attachments if a.modality is not None}
    optical_like = mods & {"optical", "multispectral", "hyperspectral"}
    return bool(optical_like) and "sar" in mods
