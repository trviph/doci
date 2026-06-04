"""Media service: upload / finalize / view / view-thumb / list / delete.

Ties together Postgres (the ``media`` table), ObjStore (presigned URLs + content
streaming), and Cache (view-URL caching in KV). Pages/thumbnails are produced by
a downstream pipeline; the view ops here read whatever rows exist.
"""

import asyncio
from collections.abc import Sequence
from uuid import UUID, uuid4

from opentelemetry.trace import SpanKind, get_current_span
from psycopg2.extras import register_uuid

from doci.cache import Cache
from doci.media.config import MediaConfig
from doci.media.mime import (
    HEADER_LEN,
    MIME_GIF,
    NETSCAPE_MARKER,
    detect_mime,
    is_gif87a,
)
from doci.media.models import (
    MediaListPage,
    MediaRecord,
    MediaStatus,
    MediaType,
    MediaView,
    UploadIntent,
)
from doci.objstore import ObjStore
from doci.postgres import Postgres
from doci.telemetry import traced, with_metrics, with_span

# Adapt uuid.UUID <-> PostgreSQL uuid (params + result columns) process-wide.
register_uuid()

_COLS = (
    "id, parent_id, type, object_key, name, mime_type, size_bytes, "
    "status, deleted_at, purge_after, created_at, updated_at"
)


class MediaError(Exception):
    """Base class for media-service errors."""


class MediaNotFound(MediaError):
    pass


class AlreadyFinalized(MediaError):
    pass


class UnsupportedType(MediaError):
    pass


class TooLarge(MediaError):
    pass


@traced
class MediaService:
    """Upload lifecycle + presigned views over the ``media`` table."""

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

    # region uploads
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def request_upload(
        self,
        *,
        name: str | None = None,
        parent_id: UUID | None = None,
        type: MediaType = MediaType.ORIGINAL,
    ) -> UploadIntent:
        """Create a `new` media row and return its presigned PUT URL."""
        mid = uuid4()
        object_key = f"{MediaType(type).key_prefix}/{mid}"
        await self._pg.execute(
            "INSERT INTO media (id, parent_id, type, object_key, name, status) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [mid, parent_id, int(type), object_key, name, int(MediaStatus.NEW)],
        )
        upload_url = await self._obj.presign_put(
            object_key, expires_in=self._cfg.upload_expiry
        )
        return UploadIntent(id=mid, upload_url=upload_url)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def finalize(self, media_id: UUID) -> MediaRecord:
        """Validate the uploaded object (MIME + size) and mark it ready/invalid."""
        _annotate(media_id)
        rec = await self._fetch(media_id)
        if rec.status is not MediaStatus.NEW:
            raise AlreadyFinalized(str(media_id))

        buf = bytearray()
        too_large = False
        async for chunk in self._obj.stream(rec.object_key):
            buf.extend(chunk)
            if len(buf) >= self._cfg.max_size:
                too_large = True
                break
        if too_large:
            await self._set_invalid(media_id)
            raise TooLarge(str(media_id))

        data = bytes(buf)
        mime = detect_mime(data, filename=rec.name)
        if mime is None:
            await self._set_invalid(media_id)
            raise UnsupportedType(str(media_id))
        if (
            mime == MIME_GIF
            and not is_gif87a(data[:HEADER_LEN])
            and NETSCAPE_MARKER in data
        ):
            await self._set_invalid(media_id)
            raise UnsupportedType(str(media_id))

        await self._pg.execute(
            "UPDATE media SET status = %s, mime_type = %s, size_bytes = %s, updated_at = now() "
            "WHERE id = %s",
            [int(MediaStatus.READY), mime, len(data), media_id],
        )
        return await self._fetch(media_id, include_deleted=True)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def download(self, media_id: UUID) -> bytes:
        """Download a media object's full body as bytes."""
        _annotate(media_id)
        rec = await self._fetch(media_id)
        return await self._obj.download(rec.object_key)

    # endregion

    # region views
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get_view(self, media_id: UUID) -> MediaView:
        """Presigned view URLs for the original + its pages."""
        _annotate(media_id)
        original = await self._fetch(media_id)
        pages = await self._children(media_id, MediaType.PAGE)
        records = [original, *pages]
        urls = await self._view_urls([r.object_key for r in records])
        views = [
            MediaView(media=r, view_url=u) for r, u in zip(records, urls, strict=True)
        ]
        return MediaView(
            media=views[0].media, view_url=views[0].view_url, children=views[1:]
        )

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get_view_thumb(self, media_id: UUID) -> MediaView:
        """Presigned view URLs for the thumb of the original + the thumb of each page."""
        _annotate(media_id)
        original = await self._fetch(media_id)
        pages = await self._children(media_id, MediaType.PAGE)
        parent_ids = [original.id, *(p.id for p in pages)]
        rows = await self._pg.fetch_all(
            f"SELECT {_COLS} FROM media "
            "WHERE parent_id = ANY(%s) AND type = %s AND deleted_at IS NULL",
            [parent_ids, int(MediaType.THUMB)],
        )
        thumb_by_parent = {
            rec.parent_id: rec for rec in (MediaRecord.from_row(r) for r in rows)
        }
        original_thumb = thumb_by_parent.get(original.id)
        if original_thumb is None:
            raise MediaNotFound(f"no thumbnail for {media_id}")
        records = [
            original_thumb,
            *(thumb_by_parent[p.id] for p in pages if p.id in thumb_by_parent),
        ]
        urls = await self._view_urls([r.object_key for r in records])
        views = [
            MediaView(media=r, view_url=u) for r, u in zip(records, urls, strict=True)
        ]
        return MediaView(
            media=views[0].media, view_url=views[0].view_url, children=views[1:]
        )

    # endregion

    # region listing / deletion
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def list_media(
        self, *, limit: int | None = None, offset: int = 0
    ) -> MediaListPage:
        """List originals (newest first), paginated."""
        lim = max(1, min(limit or self._cfg.page_size, self._cfg.max_page_size))
        offset = max(0, offset)
        rows = await self._pg.fetch_all(
            f"SELECT {_COLS} FROM media WHERE type = %s AND deleted_at IS NULL "
            "ORDER BY created_at DESC, id LIMIT %s OFFSET %s",
            [int(MediaType.ORIGINAL), lim + 1, offset],
        )
        has_more = len(rows) > lim
        items = [MediaRecord.from_row(r) for r in rows[:lim]]
        return MediaListPage(items=items, limit=lim, offset=offset, has_more=has_more)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def delete(self, ids: Sequence[UUID]) -> int:
        """Soft-delete one or many media plus their descendants. Returns the count."""
        id_list = list(ids)
        if not id_list:
            return 0
        rows = await self._pg.fetch_all(
            """
            WITH RECURSIVE subtree(id, depth) AS (
                SELECT id, 0 FROM media WHERE id = ANY(%(ids)s)
                UNION ALL
                SELECT m.id, s.depth + 1 FROM media m JOIN subtree s ON m.parent_id = s.id
                WHERE s.depth < %(max_depth)s
            )
            UPDATE media SET deleted_at = now(),
                             purge_after = now() + %(purge)s * interval '1 second',
                             updated_at = now()
            WHERE id IN (SELECT id FROM subtree) AND deleted_at IS NULL
            RETURNING id
            """,
            {
                "ids": id_list,
                "max_depth": self._cfg.delete_max_depth,
                "purge": self._cfg.purge_after,
            },
        )
        return len(rows)

    # endregion

    # region internals
    async def _fetch(
        self, media_id: UUID, *, include_deleted: bool = False
    ) -> MediaRecord:
        query = f"SELECT {_COLS} FROM media WHERE id = %s"
        if not include_deleted:
            query += " AND deleted_at IS NULL"
        row = await self._pg.fetch_one(query, [media_id])
        if row is None:
            raise MediaNotFound(str(media_id))
        return MediaRecord.from_row(row)

    async def _children(self, parent_id: UUID, mtype: MediaType) -> list[MediaRecord]:
        rows = await self._pg.fetch_all(
            f"SELECT {_COLS} FROM media "
            "WHERE parent_id = %s AND type = %s AND deleted_at IS NULL "
            "ORDER BY created_at, id",
            [parent_id, int(mtype)],
        )
        return [MediaRecord.from_row(r) for r in rows]

    async def _set_invalid(self, media_id: UUID) -> None:
        await self._pg.execute(
            "UPDATE media SET status = %s, updated_at = now() WHERE id = %s",
            [int(MediaStatus.INVALID), media_id],
        )

    async def _view_urls(self, object_keys: list[str]) -> list[str]:
        sem = asyncio.Semaphore(self._cfg.concurrency)

        async def one(key: str) -> str:
            async with sem:
                return await self._view_url(key)

        return list(await asyncio.gather(*(one(k) for k in object_keys)))

    async def _view_url(self, object_key: str) -> str:
        hit = await self._cache.get(object_key)
        if hit is not None:
            return hit
        url = await self._obj.presign_get(object_key, expires_in=self._cfg.view_expiry)
        await self._cache.set(object_key, url, ttl=self._cfg.view_cache_ttl)
        return url

    # endregion


def _annotate(media_id: UUID) -> None:
    get_current_span().set_attribute("media.id", str(media_id))
