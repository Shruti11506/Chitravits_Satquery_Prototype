"""Permitted-parameter schema for tools (mentor requirement #4).

Parameters passed to any tool must come from a fixed allow-list per tool — the
planner (and, later, any LLM-driven planner) may not invent arbitrary tool
parameters. ``sanitize_params`` keeps only allowed keys, validates their values
against a small set of constraints, and reports every key it dropped so the
rejection is auditable in the execution trace rather than silent.

The schema is intentionally static config, like the tool registry: adding a
parameter to a tool means adding it here, not letting callers pass anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ParamSpec:
    """One permitted parameter: its name and an optional value validator."""

    name: str
    validator: Callable[[Any], bool] | None = None  # returns True if the value is allowed


@dataclass(frozen=True)
class ToolParamSchema:
    """The complete set of permitted parameters for one tool."""

    allowed: dict[str, ParamSpec] = field(default_factory=dict)

    @classmethod
    def of(cls, *specs: ParamSpec) -> "ToolParamSchema":
        return cls(allowed={s.name: s for s in specs})


# --- reusable validators ---------------------------------------------------

_BANDS = frozenset({"VV", "VH", "HH", "HV"})
_ROLES = frozenset({"before", "after", "reference"})
_INDICES = frozenset({"ndvi", "ndwi", "mndwi", "ndbi", "ndmi", "nbr", "savi", "evi", "bai"})


def _is_band(v: Any) -> bool:
    return isinstance(v, str) and v.upper() in _BANDS


def _is_role(v: Any) -> bool:
    return isinstance(v, str) and v.lower() in _ROLES


def _is_index(v: Any) -> bool:
    return isinstance(v, str) and v.lower() in _INDICES


def _is_unit_fraction(v: Any) -> bool:
    return isinstance(v, (int, float)) and 0.0 <= float(v) <= 1.0


def _is_str(v: Any) -> bool:
    return isinstance(v, str) and bool(v)


def _is_bool(v: Any) -> bool:
    return isinstance(v, bool)


def _is_patch_size(v: Any) -> bool:
    """A tiling patch size the MCD-Mamba wrapper accepts."""
    return isinstance(v, int) and not isinstance(v, bool) and 32 <= v <= 2048


def _is_stride(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 2048


def _is_max_points(v: Any) -> bool:
    """Polygon contour vertex cap for GeoGround."""
    return isinstance(v, int) and not isinstance(v, bool) and 3 <= v <= 1000


# --- per-tool schemas ------------------------------------------------------
# Keyed by ToolSpec.tool_name. Spectral index tools (ndvi, ndwi, …) and their
# "*_difference" variants share a schema resolved by prefix in ``schema_for``.

_SPECTRAL_SCHEMA = ToolParamSchema.of(
    ParamSpec("threshold", _is_unit_fraction),
)
_SPECTRAL_DIFF_SCHEMA = ToolParamSchema.of(
    ParamSpec("index", _is_index),
    ParamSpec("before", _is_str),
    ParamSpec("after", _is_str),
    ParamSpec("threshold", _is_unit_fraction),
)
_SAR_SCHEMA = ToolParamSchema.of(
    ParamSpec("band", _is_band),
    ParamSpec("role", _is_role),
    ParamSpec("threshold", _is_unit_fraction),
)

TOOL_PARAM_SCHEMAS: dict[str, ToolParamSchema] = {
    # Model tools: the query, the image and any upstream evidence travel as
    # typed client arguments, never through this dict. Only the few knobs the
    # remote wrapper APIs actually expose are permitted here, so the planner
    # cannot invent an API parameter.
    "earthmind": ToolParamSchema.of(
        ParamSpec("role", _is_role),
    ),
    "mcd_mamba": ToolParamSchema.of(
        ParamSpec("patch_size", _is_patch_size),
        ParamSpec("stride", _is_stride),
    ),
    "geoground": ToolParamSchema.of(
        ParamSpec("target", _is_str),
        ParamSpec("max_points", _is_max_points),
        ParamSpec("generate_caption", _is_bool),
    ),
    # Deterministic SAR tools.
    "sar_otsu": _SAR_SCHEMA,
    "sar_db": _SAR_SCHEMA,
    "vv_vh": _SAR_SCHEMA,
}


def schema_for(tool_name: str) -> ToolParamSchema:
    """Return the permitted-parameter schema for a tool, resolving spectral variants."""
    if tool_name in TOOL_PARAM_SCHEMAS:
        return TOOL_PARAM_SCHEMAS[tool_name]
    if tool_name.endswith("_difference"):
        return _SPECTRAL_DIFF_SCHEMA
    if tool_name in _INDICES:
        return _SPECTRAL_SCHEMA
    # Unknown tool: no params permitted (fail closed).
    return ToolParamSchema.of()


def sanitize_params(tool_name: str, params: dict) -> tuple[dict, list[str]]:
    """Filter ``params`` to the tool's allow-list.

    Returns ``(clean_params, rejected)`` where ``rejected`` lists every key that
    was dropped — either because it is not in the allow-list or because its value
    failed the parameter's validator. Callers surface ``rejected`` as a warning.
    """
    schema = schema_for(tool_name)
    clean: dict = {}
    rejected: list[str] = []
    for key, value in (params or {}).items():
        spec = schema.allowed.get(key)
        if spec is None:
            rejected.append(key)
            continue
        if spec.validator is not None and not spec.validator(value):
            rejected.append(f"{key}={value!r}")
            continue
        clean[key] = value
    return clean, rejected
