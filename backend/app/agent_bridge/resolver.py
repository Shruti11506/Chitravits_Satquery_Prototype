"""Supabase-backed attachment resolver for the SatQuery agent.

The agent resolves an ``AttachmentRef`` to raw image bytes through a duck-typed
resolver exposing ``async resolve(attachment) -> ResolvedImage``. This one maps
``attachment.id`` (an imagery row id) to its stored object and downloads the
bytes from Supabase Storage. It is stateless: any job can share one instance.

supabase-py is synchronous, so the blocking download runs in a worker thread to
avoid stalling the agent's event loop.
"""
from __future__ import annotations

import logging

import anyio

from app.db.supabase import get_supabase
from app.services import imagery_service, storage_service

# Reuse the agent's own result/error types so the agent can't tell this
# resolver apart from its built-in one.
from satquery.agent.tools.attachment_resolver import AttachmentResolutionError, ResolvedImage

logger = logging.getLogger(__name__)


class SupabaseAttachmentResolver:
    """Resolves imagery-id attachments to bytes from Supabase Storage."""

    async def resolve(self, attachment) -> ResolvedImage:
        imagery_id = attachment.id
        try:
            row = await anyio.to_thread.run_sync(imagery_service.get_imagery, imagery_id)
        except Exception as exc:  # noqa: BLE001 - NotFoundError, SupabaseError, ...
            raise AttachmentResolutionError(
                "ATTACHMENT_NOT_FOUND",
                f"Imagery '{imagery_id}' could not be loaded: {exc}",
            ) from exc

        storage_path = row.get("storage_path")
        if not storage_path:
            raise AttachmentResolutionError(
                "ATTACHMENT_UNRESOLVABLE",
                f"Imagery '{imagery_id}' has no storage_path.",
            )

        client = get_supabase()
        try:
            data = await anyio.to_thread.run_sync(
                storage_service.download_file, client, storage_path
            )
        except Exception as exc:  # noqa: BLE001 - StorageError, network, ...
            raise AttachmentResolutionError(
                "ATTACHMENT_NOT_FOUND",
                f"Could not download imagery '{imagery_id}' from storage: {exc}",
            ) from exc

        if not data:
            raise AttachmentResolutionError("INVALID_IMAGE", "The stored image is empty.")

        return ResolvedImage(data=bytes(data), source_hint="supabase")
