"""Business logic for projects: workspaces that group chats, knowledge files and instructions.

Ownership: every project belongs to a profile -- today the single workspace
profile from profile_service.get_current_profile (the app has no login yet),
later a real user. Every read and write is scoped to that owner, so another
profile's project is simply "not found".

Counts are computed from rows, never stored:
* chat_count  -- the project's started conversations (an upload or a query),
                 the same rule the sidebar uses to list a conversation;
* file_count  -- knowledge files uploaded to the project, plus images uploaded
                 in its chats.

Deleting a project keeps its chats (they return to the normal history) and
deletes only the project's own knowledge files.
"""
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.core.exceptions import (
    NotFoundError,
    SchemaNotMigratedError,
    StorageError,
    SupabaseError,
    ValidationAppError,
)
from app.db.supabase import execute_read, get_supabase
from app.schemas.projects import ProjectCreate, ProjectUpdate
from app.services import conversation_service, profile_service, storage_service

logger = logging.getLogger(__name__)

TABLE = "projects"
FILES_TABLE = "project_files"

MIGRATION_HINT = (
    "Projects are not set up yet: apply "
    "backend/supabase/migrations/0008_projects.sql in the Supabase SQL editor."
)
# Missing table (PGRST205/42P01) or column (PGRST204/42703).
_MISSING_SCHEMA_CODES = {"PGRST205", "42P01", "PGRST204", "42703"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _raise_supabase(exc: Exception, message: str):
    if getattr(exc, "code", None) in _MISSING_SCHEMA_CODES:
        raise SchemaNotMigratedError(MIGRATION_HINT) from exc
    raise SupabaseError(message) from exc


def _owner_id() -> str:
    return profile_service.get_current_profile()["id"]


def _clean_name(name: str | None) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise ValidationAppError("INVALID_PROJECT_NAME", "Project name cannot be empty.")
    return cleaned


def _clean_text(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def get_owned_project(project_id: str) -> dict:
    """The project row, if it exists AND belongs to the current profile; else 404."""
    client = get_supabase()
    try:
        response = execute_read(
            client.table(TABLE).select("*").eq("id", project_id).eq("profile_id", _owner_id()).maybe_single()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase get failed for project %s", project_id)
        _raise_supabase(exc, "Failed to fetch project.")
    if not response or not response.data:
        raise NotFoundError("PROJECT_NOT_FOUND", f"Project '{project_id}' was not found.")
    return response.data


def _select_in(table: str, columns: str, column: str, values: list[str]) -> list[dict]:
    if not values:
        return []
    client = get_supabase()
    try:
        return execute_read(client.table(table).select(columns).in_(column, values)).data or []
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase read failed for %s", table)
        _raise_supabase(exc, "Failed to load project contents.")


def _with_counts(projects: list[dict]) -> list[dict]:
    """Add chat_count / file_count / has_custom_instructions from the related rows."""
    ids = [p["id"] for p in projects]
    conversations = _select_in("conversations", "id,project_id", "project_id", ids)
    started = conversation_service.ids_with_content([c["id"] for c in conversations])
    project_of = {c["id"]: c["project_id"] for c in conversations}
    chat_images = _select_in("imagery", "conversation_id", "conversation_id", list(project_of))
    files = _select_in(FILES_TABLE, "project_id", "project_id", ids)

    chats: dict[str, int] = {}
    file_counts: dict[str, int] = {}
    for conversation_id in started:
        chats[project_of[conversation_id]] = chats.get(project_of[conversation_id], 0) + 1
    for image in chat_images:
        owner = project_of[image["conversation_id"]]
        file_counts[owner] = file_counts.get(owner, 0) + 1
    for row in files:
        file_counts[row["project_id"]] = file_counts.get(row["project_id"], 0) + 1

    return [
        {
            **p,
            "chat_count": chats.get(p["id"], 0),
            "file_count": file_counts.get(p["id"], 0),
            "has_custom_instructions": bool((p.get("custom_instructions") or "").strip()),
        }
        for p in projects
    ]


def list_projects() -> list[dict]:
    """The current profile's projects, most recently updated first, with real counts."""
    client = get_supabase()
    try:
        response = execute_read(
            client.table(TABLE).select("*").eq("profile_id", _owner_id()).order("updated_at", desc=True)
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase list failed for projects")
        _raise_supabase(exc, "Failed to list projects.")
    return _with_counts(response.data or [])


def get_project_detail(project_id: str) -> dict:
    """The project with its chats (started, newest first), knowledge files and chat uploads."""
    project = _with_counts([get_owned_project(project_id)])[0]
    client = get_supabase()

    try:
        conversations = execute_read(
            client.table("conversations").select("*").eq("project_id", project_id).order("updated_at", desc=True)
        ).data or []
        files = execute_read(
            client.table(FILES_TABLE).select("*").eq("project_id", project_id).order("created_at", desc=True)
        ).data or []
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase read failed for project %s", project_id)
        _raise_supabase(exc, "Failed to load project contents.")

    started = conversation_service.ids_with_content([c["id"] for c in conversations])
    conversations = [c for c in conversations if c["id"] in started]
    titles = {c["id"]: c["title"] for c in conversations}
    images = _select_in(
        "imagery", "id,conversation_id,original_filename,name,file_size,created_at", "conversation_id", list(titles)
    )

    return {
        **project,
        "conversations": conversations,
        "files": [{**f, "url": storage_service.resolve_url(client, f.get("storage_path"))} for f in files],
        "chat_uploads": sorted(
            (
                {
                    "imagery_id": image["id"],
                    "conversation_id": image["conversation_id"],
                    "conversation_title": titles.get(image["conversation_id"]),
                    "name": image.get("original_filename") or image.get("name"),
                    "file_size": image.get("file_size"),
                    "created_at": image.get("created_at"),
                }
                for image in images
            ),
            key=lambda u: u["created_at"] or "",
            reverse=True,
        ),
    }


def get_project(project_id: str) -> dict:
    return _with_counts([get_owned_project(project_id)])[0]


def create_project(payload: ProjectCreate) -> dict:
    client = get_supabase()
    now = _now()
    row = {
        "profile_id": _owner_id(),
        "name": _clean_name(payload.name),
        "description": _clean_text(payload.description),
        "icon": _clean_text(payload.icon),
        "color": _clean_text(payload.color),
        "custom_instructions": _clean_text(payload.custom_instructions),
        "created_at": now,
        "updated_at": now,
    }
    try:
        response = client.table(TABLE).insert(row).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase insert failed for projects")
        _raise_supabase(exc, "Failed to create project.")
    if not response.data:
        raise SupabaseError("Project insert returned no data.")
    return _with_counts(response.data)[0]


def update_project(project_id: str, payload: ProjectUpdate) -> dict:
    get_owned_project(project_id)
    changes: dict[str, Any] = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        changes[field] = _clean_name(value) if field == "name" else _clean_text(value)
    if not changes:
        return get_project(project_id)
    changes["updated_at"] = _now()

    client = get_supabase()
    try:
        response = client.table(TABLE).update(changes).eq("id", project_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase update failed for project %s", project_id)
        _raise_supabase(exc, "Failed to update project.")
    if not response.data:
        raise NotFoundError("PROJECT_NOT_FOUND", f"Project '{project_id}' was not found.")
    return _with_counts(response.data)[0]


def touch(project_id: str) -> None:
    """Bump updated_at (a chat or file was added/removed). Best-effort."""
    try:
        get_supabase().table(TABLE).update({"updated_at": _now()}).eq("id", project_id).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to bump updated_at for project %s", project_id)


def delete_project(project_id: str) -> None:
    """Delete the project and its knowledge files; its chats are kept (project_id cleared).

    DB first, then Storage (same order as imagery): the database's FKs do the
    same (ON DELETE SET NULL / CASCADE), but the steps are explicit so the
    outcome never depends on how a given database was migrated.
    """
    get_owned_project(project_id)
    client = get_supabase()
    try:
        files = execute_read(client.table(FILES_TABLE).select("storage_path").eq("project_id", project_id)).data or []
        client.table("conversations").update({"project_id": None}).eq("project_id", project_id).execute()
        client.table(FILES_TABLE).delete().eq("project_id", project_id).execute()
        client.table(TABLE).delete().eq("id", project_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase delete failed for project %s", project_id)
        _raise_supabase(exc, "Failed to delete project.")

    for row in files:
        try:
            storage_service.delete_file(client, row["storage_path"])
        except StorageError:
            logger.error("Project %s deleted but its file %s could not be removed -- orphaned.", project_id, row["storage_path"])


def add_file(project_id: str, filename: str, content: bytes) -> dict:
    """Upload a knowledge file to Storage (projects/{project_id}/...) and record it."""
    get_owned_project(project_id)
    content_type = storage_service.validate_project_file(filename, len(content))
    client = get_supabase()
    settings = get_settings()
    storage_path = storage_service.build_storage_path(filename, prefix=f"{storage_service.PROJECTS_PREFIX}/{project_id}")

    storage_service.upload_file(client, storage_path, content, content_type)
    row = {
        "project_id": project_id,
        "name": filename,
        "bucket": settings.SUPABASE_STORAGE_BUCKET,
        "storage_path": storage_path,
        "mime_type": content_type,
        "file_size": len(content),
        "created_at": _now(),
    }
    try:
        response = client.table(FILES_TABLE).insert(row).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase insert failed for project file %s", storage_path)
        try:
            storage_service.delete_file(client, storage_path)  # no row -> don't keep the object
        except StorageError:
            logger.error("Could not remove %s after a failed insert -- orphaned file.", storage_path)
        _raise_supabase(exc, "File uploaded to Storage but failed to save its record.")
    if not response.data:
        raise SupabaseError("Project file insert returned no data.")
    touch(project_id)
    created = response.data[0]
    return {**created, "url": storage_service.resolve_url(client, storage_path)}


def delete_file(project_id: str, file_id: str) -> None:
    get_owned_project(project_id)
    client = get_supabase()
    try:
        response = execute_read(
            client.table(FILES_TABLE).select("*").eq("id", file_id).eq("project_id", project_id).maybe_single()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase get failed for project file %s", file_id)
        _raise_supabase(exc, "Failed to fetch project file.")
    if not response or not response.data:
        raise NotFoundError("PROJECT_FILE_NOT_FOUND", f"File '{file_id}' was not found in this project.")

    try:
        client.table(FILES_TABLE).delete().eq("id", file_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase delete failed for project file %s", file_id)
        _raise_supabase(exc, "Failed to delete project file.")
    storage_service.delete_file(client, response.data["storage_path"])
    touch(project_id)
