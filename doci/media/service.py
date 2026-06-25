"""Media service: pure blob storage over Postgres + ObjStore + Cache.

``media`` is just objects in the store: an ``object_key`` plus content metadata
(MIME, size) and soft-delete/purge bookkeeping. The document domain — originals,
pages, regions, upload/validation lifecycle — lives in :mod:`doci.documents`,
which composes these blob primitives.

Idempotency is keyed on ``object_key`` (``UNIQUE``): callers derive deterministic
keys (see :mod:`doci.documents`), so re-creating a blob upserts the same row and
overwrites the same object. The higher layer skips the work entirely on a rerun
by checking its own rows first.
"""

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

from opentelemetry.trace import SpanKind, get_current_span

from doci.cache import Cache
from doci.helpers import internal
from doci.media.config import MediaConfig
from doci.media.mime import (
    HEADER_LEN,
    MIME_GIF,
    NETSCAPE_MARKER,
    detect_mime,
    is_gif87a,
)
from doci.media.models import MediaRecord
from doci.objstore import ObjStore
from doci.postgres import Postgres, Transaction
from doci.telemetry import traced, with_metrics, with_span


#: An object that can run statements — the pool (auto-commit per call) or an open
#: transaction. Both expose the same ``execute``/``fetch_*`` surface, so a caller
#: can compose a blob write into its own transaction by passing the latter.
Executor = Postgres | Transaction

#: A coroutine producing ``(bytes, mime_type)`` — deferred so it runs only when a
#: blob actually needs creating (skipped on the idempotent fast path).
Render = Callable[[], Awaitable[tuple[bytes, str | None]]]

_COLS = (
    "id, object_key, mime_type, size_bytes, "
    "deleted_at, purge_after, created_at, updated_at"
)


class MediaError(Exception):
    """Base class for media-service errors."""


class MediaNotFound(MediaError):
    pass


class UnsupportedType(MediaError):
    pass


class TooLarge(MediaError):
    pass


@traced
class MediaService:
    """Blob lifecycle + presigned views over the ``media`` table."""

    def __init__(
        self,
        *,
        postgres: Postgres,
        objstore: ObjStore,
        cache: Cache,
        config: MediaConfig,
    ) -> None:
        self._pg = postgres
        self._obj = objstore
        self._cache = cache
        self._cfg = config

    # region blob primitives
    async def presign_put(self, object_key: str) -> str:
        """Presigned PUT URL for a client-side upload to ``object_key``."""
        return await self._obj.presign_put(
            object_key, expires_in=self._cfg.upload_expiry
        )

    @internal
    async def upload_object(
        self, object_key: str, data: bytes, mime: str | None
    ) -> None:
        """Store server-generated ``data`` at ``object_key`` (S3 only; no DB write).

        Internal-only: client uploads go through a presigned PUT
        (:meth:`presign_put`), never the server.
        """
        await self._obj.upload(object_key, data, content_type=mime)

    async def insert_blob(
        self,
        executor: Executor,
        *,
        object_key: str,
        media_id: UUID | None = None,
        mime: str | None = None,
        size: int | None = None,
    ) -> MediaRecord:
        """Upsert a ``media`` row for ``object_key`` and return it.

        Idempotent on ``object_key``: a second insert for the same key updates the
        existing row's MIME/size rather than creating a duplicate. Runs on the
        given ``executor`` so the caller can include it in a transaction.
        """
        row = await executor.fetch_one(
            f"INSERT INTO media (id, object_key, mime_type, size_bytes) "
            f"VALUES (%s, %s, %s, %s) "
            f"ON CONFLICT (object_key) DO UPDATE "
            f"SET mime_type = EXCLUDED.mime_type, size_bytes = EXCLUDED.size_bytes, "
            f"    updated_at = now() "
            f"RETURNING {_COLS}",
            [media_id or uuid4(), object_key, mime, size],
        )
        return MediaRecord.from_row(row)

    async def validate_object(
        self, object_key: str, *, name: str | None = None
    ) -> tuple[str, int]:
        """Stream the stored object, validate MIME + size, return ``(mime, size)``.

        Raises :class:`TooLarge` past the configured size cap, or
        :class:`UnsupportedType` for an undetectable/blocked MIME.
        """
        buf = bytearray()
        too_large = False
        async for chunk in self._obj.stream(object_key):
            buf.extend(chunk)
            if len(buf) >= self._cfg.max_size:
                too_large = True
                break
        if too_large:
            raise TooLarge(object_key)

        data = bytes(buf)
        mime = detect_mime(data, filename=name)
        if mime is None:
            raise UnsupportedType(object_key)
        if (
            mime == MIME_GIF
            and not is_gif87a(data[:HEADER_LEN])
            and NETSCAPE_MARKER in data
        ):
            raise UnsupportedType(object_key)
        return mime, len(data)

    @internal
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def ensure_thumb(self, source_media_id: UUID, render: Render) -> MediaRecord:
        """Idempotently create the thumbnail blob for ``source_media_id``.

        The thumb's key is derived from its source's (``{source_key}.thumb``), so
        it needs no document/region context. If the thumb already exists,
        ``render`` is never called and nothing is uploaded; otherwise the rendered
        bytes are stored and a row upserted. Document-agnostic by design — the same
        method serves a standalone image, a split PDF page, or any region blob.
        """
        src = await self._fetch(source_media_id)
        thumb_key = f"{src.object_key}.thumb"
        existing = await self._pg.fetch_one(
            f"SELECT {_COLS} FROM media WHERE object_key = %s AND deleted_at IS NULL",
            [thumb_key],
        )
        if existing is not None:
            return MediaRecord.from_row(existing)
        data, mime = await render()
        await self.upload_object(thumb_key, data, mime)
        return await self.insert_blob(
            self._pg, object_key=thumb_key, mime=mime, size=len(data)
        )

    # endregion

    # region reads
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get(self, media_id: UUID) -> MediaRecord:
        """Fetch a (non-deleted) media record by id."""
        _annotate(media_id)
        return await self._fetch(media_id)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def download(self, media_id: UUID) -> bytes:
        """Download a media object's full body as bytes."""
        _annotate(media_id)
        rec = await self._fetch(media_id)
        return await self._obj.download(rec.object_key)

    async def get_many(self, ids: list[UUID]) -> dict[UUID, MediaRecord]:
        """Fetch the (non-deleted) media rows for ``ids``, keyed by id."""
        if not ids:
            return {}
        rows = await self._pg.fetch_all(
            f"SELECT {_COLS} FROM media WHERE id = ANY(%s) AND deleted_at IS NULL",
            [ids],
        )
        return {r["id"]: MediaRecord.from_row(r) for r in rows}

    async def view_url(self, object_key: str) -> str:
        """Cache-backed presigned GET URL for ``object_key``."""
        hit = await self._cache.get(object_key)
        if hit is not None:
            return hit
        url = await self._obj.presign_get(object_key, expires_in=self._cfg.view_expiry)
        await self._cache.set(object_key, url, ttl=self._cfg.view_cache_ttl)
        return url

    async def view_urls(self, object_keys: list[str]) -> list[str]:
        """Presigned GET URLs for many keys, bounded by the configured concurrency."""
        sem = asyncio.Semaphore(self._cfg.concurrency)

        async def one(key: str) -> str:
            async with sem:
                return await self.view_url(key)

        return list(await asyncio.gather(*(one(k) for k in object_keys)))

    # endregion

    # region purge
    @internal
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def purge_expired(self) -> int:
        """Hard-delete media whose purge deadline has passed; objects first.

        Each S3 object is deleted first; the matching DB row is removed only once
        its object is gone, so a transient store failure simply leaves the row for
        the next sweep instead of orphaning the object. Removing a ``media`` row
        cascades to the ``document`` / ``document_part`` rows that reference it.
        Returns the number of rows hard-deleted.
        """
        rows = await self._pg.fetch_all(
            "SELECT id, object_key FROM media "
            "WHERE purge_after IS NOT NULL AND purge_after <= now()"
        )
        if not rows:
            return 0

        span = get_current_span()
        sem = asyncio.Semaphore(self._cfg.concurrency)

        async def purge_one(row: dict) -> UUID | None:
            async with sem:
                try:
                    await self._obj.delete(row["object_key"])
                except Exception as exc:  # leave the row for the next sweep
                    span.record_exception(exc)
                    return None
                return row["id"]

        purged = await asyncio.gather(*(purge_one(r) for r in rows))
        ids = [i for i in purged if i is not None]
        if not ids:
            return 0
        deleted = await self._pg.fetch_all(
            "DELETE FROM media WHERE id = ANY(%s) RETURNING id", [ids]
        )
        return len(deleted)

    # endregion

    # region internals
    async def _fetch(self, media_id: UUID) -> MediaRecord:
        row = await self._pg.fetch_one(
            f"SELECT {_COLS} FROM media WHERE id = %s AND deleted_at IS NULL",
            [media_id],
        )
        if row is None:
            raise MediaNotFound(str(media_id))
        return MediaRecord.from_row(row)

    # endregion


def _annotate(media_id: UUID) -> None:
    get_current_span().set_attribute("media.id", str(media_id))
