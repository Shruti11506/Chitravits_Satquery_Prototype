"""Business logic for the conversations resource.

A conversation groups a chat's uploads (imagery.conversation_id) and queries
(analysis_jobs.conversation_id). Title rules:

* A new conversation is titled "New Chat" (title_source "default").
* Uploading files never changes the title.
* `generate_title` sets the title ONCE from the conversation's first
  meaningful query (title_source "auto"), and is a no-op afterwards.
* A manual rename sets title_source "user"; it is never overwritten.
"""
import logging
from datetime import datetime, timezone

from app.core.exceptions import NotFoundError, SupabaseError, ValidationAppError
from app.db.supabase import execute_read, get_supabase
from app.schemas.conversations import DEFAULT_CONVERSATION_TITLE, TitleSource
from app.services import imagery_service, storage_service, title_service

logger = logging.getLogger(__name__)

TABLE = "conversations"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_conversation(project_id: str | None = None) -> dict:
    """A new "New Chat"; inside a project when project_id is given (it must be the caller's)."""
    # Imported here: project_service imports this module for ids_with_content.
    from app.services import project_service

    if project_id:
        project_service.get_owned_project(project_id)  # 404 PROJECT_NOT_FOUND before any write

    client = get_supabase()
    now = _now()
    row = {
        "title": DEFAULT_CONVERSATION_TITLE,
        "title_source": TitleSource.DEFAULT.value,
        "created_at": now,
        "updated_at": now,
    }
    if project_id:
        row["project_id"] = project_id  # only then, so ordinary chats never need migration 0008
    try:
        response = client.table(TABLE).insert(row).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase insert failed for conversations")
        raise SupabaseError("Failed to create conversation.") from exc

    if not response.data:
        raise SupabaseError("Conversation insert returned no data.")
    if project_id:
        project_service.touch(project_id)
    return response.data[0]


def ids_with_content(conversation_ids: list[str]) -> set[str]:
    """The subset of `conversation_ids` that has at least one upload or query."""
    if not conversation_ids:
        return set()
    client = get_supabase()
    found: set[str] = set()
    for table in ("imagery", "analysis_jobs"):
        try:
            response = execute_read(
                client.table(table)
                .select("conversation_id")
                .in_("conversation_id", conversation_ids)
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Supabase read failed for %s conversation ids", table)
            raise SupabaseError("Failed to list conversations.") from exc
        found.update(row["conversation_id"] for row in response.data or [])
    return found


def list_conversations(limit: int = 100) -> list[dict]:
    """Started conversations, most recently active first.

    updated_at is bumped by uploads and queries. A conversation with no upload
    and no query yet is not listed: the frontend creates the row only on the
    first upload, so an empty one is either that upload still in flight or a
    blank "New Chat" left by the old eager-create behaviour (see
    `purge_empty_conversations`).
    """
    client = get_supabase()
    try:
        response = execute_read(
            client.table(TABLE).select("*").order("updated_at", desc=True).limit(limit)
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase list failed for conversations")
        raise SupabaseError("Failed to list conversations.") from exc
    rows = response.data or []
    started = ids_with_content([row["id"] for row in rows])
    return [row for row in rows if row["id"] in started]


def purge_empty_conversations(older_than_minutes: int = 60, apply: bool = False) -> list[dict]:
    """Find (and, with apply=True, delete) conversations with no uploads and no queries.

    Only rows older than `older_than_minutes` qualify, so a conversation
    whose first upload is still in flight is never touched. Each row is
    re-checked immediately before its delete; the imagery/analysis_jobs
    foreign keys (no ON DELETE action) would also make the delete fail if
    content arrived in between. Returns the matching rows.
    """
    client = get_supabase()
    cutoff = datetime.now(timezone.utc).timestamp() - older_than_minutes * 60
    try:
        rows = execute_read(client.table(TABLE).select("*")).data or []
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase list failed for conversations")
        raise SupabaseError("Failed to list conversations.") from exc

    old = [
        row for row in rows
        if datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")).timestamp() < cutoff
    ]
    started = ids_with_content([row["id"] for row in old])
    empty = [row for row in old if row["id"] not in started]
    if not apply:
        return empty

    purged = []
    for row in empty:
        if ids_with_content([row["id"]]):
            continue
        try:
            client.table(TABLE).delete().eq("id", row["id"]).execute()
        except Exception:  # noqa: BLE001
            logger.exception("Could not delete empty conversation %s", row["id"])
            continue
        purged.append(row)
    return purged


def get_conversation(conversation_id: str) -> dict:
    client = get_supabase()
    try:
        response = (
            client.table(TABLE).select("*").eq("id", conversation_id).maybe_single().execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase get failed for conversation %s", conversation_id)
        raise SupabaseError("Failed to fetch conversation.") from exc

    if not response or not response.data:
        raise NotFoundError(
            "CONVERSATION_NOT_FOUND", f"Conversation '{conversation_id}' was not found."
        )
    return response.data


def _select_for_conversation(table: str, conversation_id: str) -> list[dict]:
    client = get_supabase()
    try:
        response = (
            client.table(table)
            .select("*")
            .eq("conversation_id", conversation_id)
            .order("created_at")
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase list failed for %s of conversation %s", table, conversation_id)
        raise SupabaseError(f"Failed to load conversation {table}.") from exc
    return response.data or []


def get_conversation_detail(conversation_id: str) -> dict:
    """The conversation plus its uploads (with fresh access URLs) and queries, oldest first."""
    conversation = get_conversation(conversation_id)
    client = get_supabase()
    imagery = []
    for stored in _select_for_conversation("imagery", conversation_id):
        row = {**stored, "url": storage_service.resolve_url(client, stored.get("storage_path"))}
        # May fill in (once) the preview of an older TIFF row -- see resolve_thumbnail_url.
        row["thumbnail_url"] = imagery_service.resolve_thumbnail_url(client, row)
        imagery.append(row)
    jobs = _select_for_conversation("analysis_jobs", conversation_id)
    return {**conversation, "imagery": imagery, "jobs": jobs}


def _update(conversation_id: str, changes: dict) -> dict:
    client = get_supabase()
    try:
        response = client.table(TABLE).update(changes).eq("id", conversation_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase update failed for conversation %s", conversation_id)
        raise SupabaseError("Failed to update conversation.") from exc

    if not response.data:
        raise NotFoundError(
            "CONVERSATION_NOT_FOUND", f"Conversation '{conversation_id}' was not found."
        )
    return response.data[0]


def touch(conversation_id: str) -> None:
    """Bump updated_at so the conversation sorts to the top of the sidebar.

    Best-effort: the upload/query that triggered it has already succeeded.
    """
    try:
        _update(conversation_id, {"updated_at": _now()})
    except Exception:  # noqa: BLE001
        logger.exception("Failed to bump updated_at for conversation %s", conversation_id)


def rename_conversation(conversation_id: str, title: str) -> dict:
    cleaned = " ".join((title or "").split())
    if not cleaned:
        raise ValidationAppError("INVALID_TITLE", "Title cannot be empty.")
    get_conversation(conversation_id)
    return _update(conversation_id, {"title": cleaned, "title_source": TitleSource.USER.value})


def generate_title(conversation_id: str) -> dict:
    """Title the conversation from its FIRST meaningful query, exactly once.

    The query is read from the stored analysis_jobs rows rather than taken
    from the client, so the title always reflects the real first query no
    matter how often (or late) this is called. No-op once the title is
    "auto" or "user", or while there is no meaningful query yet.
    """
    conversation = get_conversation(conversation_id)
    if conversation.get("title_source") != TitleSource.DEFAULT.value:
        return conversation

    for job in _select_for_conversation("analysis_jobs", conversation_id):
        title = title_service.generate_conversation_title(job.get("query"))
        if title:
            return _update(
                conversation_id, {"title": title, "title_source": TitleSource.AUTO.value}
            )
    return conversation


def _delete_jobs(job_ids: list[str]) -> None:
    """Delete analysis jobs together with their results and evidence.

    Order matters because of foreign keys: evidence -> analysis_results ->
    analysis_jobs. A completed job has an analysis_results row, so deleting the
    job first fails with an FK violation ("Failed to delete conversation
    queries.").
    """
    if not job_ids:
        return
    client = get_supabase()
    try:
        results = client.table("analysis_results").select("id").in_("job_id", job_ids).execute()
        result_ids = [r["id"] for r in results.data or []]
        if result_ids:
            client.table("evidence").delete().in_("result_id", result_ids).execute()
            client.table("analysis_results").delete().in_("id", result_ids).execute()
        client.table("analysis_jobs").delete().in_("id", job_ids).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to delete analysis_jobs %s", job_ids)
        raise SupabaseError("Failed to delete conversation queries.") from exc


def delete_conversation(conversation_id: str) -> None:
    """Delete the conversation with its queries and uploads (rows + Storage files).

    Order matters because of foreign keys: jobs (with their results, see
    _delete_jobs) go first because analysis_jobs -> imagery, then each imagery
    (DB row, then Storage object -- see imagery_service.delete_imagery), then
    the conversation itself.
    """
    get_conversation(conversation_id)
    client = get_supabase()

    _delete_jobs([row["id"] for row in _select_for_conversation("analysis_jobs", conversation_id)])

    for row in _select_for_conversation("imagery", conversation_id):
        imagery_service.delete_imagery(row["id"])

    try:
        client.table(TABLE).delete().eq("id", conversation_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase delete failed for conversation %s", conversation_id)
        raise SupabaseError("Failed to delete conversation.") from exc


def _select_jobs_using_imagery(imagery_id: str) -> list[dict]:
    client = get_supabase()
    try:
        primary = client.table("analysis_jobs").select("*").eq("imagery_id", imagery_id).execute()
        comparison = (
            client.table("analysis_jobs").select("*").eq("comparison_imagery_id", imagery_id).execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase list failed for analysis_jobs of imagery %s", imagery_id)
        raise SupabaseError("Failed to load imagery queries.") from exc
    return (primary.data or []) + (comparison.data or [])


def delete_legacy_chat(imagery_id: str) -> None:
    """Delete a legacy chat: the queries made against one image before
    conversations existed (analysis_jobs with conversation_id NULL), their
    results, and the image(s) they used once nothing else references them.
    """
    jobs = [
        job
        for job in _select_jobs_using_imagery(imagery_id)
        if job.get("imagery_id") == imagery_id and not job.get("conversation_id")
    ]
    if not jobs:
        raise NotFoundError("CHAT_NOT_FOUND", "Chat not found.")

    used_imagery = {imagery_id} | {j["comparison_imagery_id"] for j in jobs if j.get("comparison_imagery_id")}
    _delete_jobs([job["id"] for job in jobs])

    for image_id in used_imagery:
        # Keep an image another query (or a conversation) still uses.
        if _select_jobs_using_imagery(image_id):
            continue
        try:
            image = imagery_service.get_imagery(image_id)
        except NotFoundError:
            continue
        if image.get("conversation_id"):
            continue
        imagery_service.delete_imagery(image_id)
