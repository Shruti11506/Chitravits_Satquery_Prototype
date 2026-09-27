"""Business logic for the Settings page (user_settings, migration 0005).

One row per profile, created lazily with DEFAULTS on first read. The acting
profile always comes from profile_service.get_current_profile -- never from
anything the client sends. Profile fields themselves live in `profiles` and
are edited through the existing /profile endpoints, not here.
"""
import logging
from datetime import datetime, timezone

from app.core.exceptions import SchemaNotMigratedError, SupabaseError
from app.db.supabase import execute_read, get_supabase
from app.schemas.settings import SettingsUpdate
from app.services import profile_service

logger = logging.getLogger(__name__)

TABLE = "user_settings"

# Same values as the column defaults in migrations/0005_user_settings.sql.
DEFAULTS = {
    "theme": "light",
    "language": "en",
    "sidebar_density": "comfortable",
    "default_data_type": "optical_rgb",
    "default_analysis_task": "scene_description",
    "notify_analysis_completion": True,
    "notify_product_updates": False,
    "notify_usage_alerts": True,
    "save_analysis_results": True,
    "share_usage_analytics": False,
}

MIGRATION_HINT = (
    "Settings are not set up yet: apply "
    "backend/supabase/migrations/0005_user_settings.sql in the Supabase SQL editor."
)
_MISSING_SCHEMA_CODES = {"PGRST205", "42P01"}


def _raise_supabase(exc: Exception, message: str):
    if getattr(exc, "code", None) in _MISSING_SCHEMA_CODES:
        raise SchemaNotMigratedError(MIGRATION_HINT) from exc
    raise SupabaseError(message) from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _select(client, profile_id: str) -> dict | None:
    try:
        response = execute_read(client.table(TABLE).select("*").eq("profile_id", profile_id).limit(1))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase read failed for user_settings")
        _raise_supabase(exc, "Failed to load settings.")
    return (response.data or [None])[0]


def get_settings_row(profile: dict) -> dict:
    """The profile's settings row, created with DEFAULTS if it doesn't exist yet."""
    client = get_supabase()
    row = _select(client, profile["id"])
    if row:
        return row

    now = _now()
    try:
        response = (
            client.table(TABLE)
            .insert({"profile_id": profile["id"], **DEFAULTS, "created_at": now, "updated_at": now})
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        # A concurrent first read may have created it (profile_id is unique).
        row = _select(client, profile["id"])
        if row:
            return row
        logger.exception("Supabase insert failed for user_settings")
        _raise_supabase(exc, "Failed to create settings.")
    if not response.data:
        raise SupabaseError("Settings insert returned no data.")
    return response.data[0]


def update_settings(profile: dict, payload: SettingsUpdate) -> dict:
    changes = payload.model_dump(exclude_none=True)
    row = get_settings_row(profile)
    if not changes:
        return row

    client = get_supabase()
    try:
        response = (
            client.table(TABLE)
            .update({**changes, "updated_at": _now()})
            .eq("id", row["id"])
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase update failed for user_settings %s", row["id"])
        _raise_supabase(exc, "Failed to save settings.")
    if not response.data:
        raise SupabaseError("Settings update returned no data.")
    return response.data[0]


def to_out(profile: dict, row: dict) -> dict:
    user = profile_service.to_public_user(profile)
    return {
        "profile": {
            "display_name": user["display_name"],
            "username": user["username"],
            "avatar_url": user["avatar_url"],
            "bio": user["bio"],
        },
        "preferences": {
            key: row[key]
            for key in ("theme", "language", "sidebar_density", "default_data_type", "default_analysis_task")
        },
        "notifications": {
            "analysis_completion": row["notify_analysis_completion"],
            "product_updates": row["notify_product_updates"],
            "usage_alerts": row["notify_usage_alerts"],
        },
        "privacy": {
            "save_analysis_results": row["save_analysis_results"],
            "share_usage_analytics": row["share_usage_analytics"],
        },
        "updated_at": row.get("updated_at"),
    }
