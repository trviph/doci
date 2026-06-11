"""Documents service: upload / finalize / regions / views over the document domain.

A ``document`` is an uploaded file; its derived regions are ``document_part`` rows.
Both reference ``media`` for bytes. This service owns the upload/validation
lifecycle (``status``) and the per-region idempotency keyed by ``locator``:

- :meth:`request_upload` / :meth:`finalize` are the client-facing presign flow.
- :meth:`ensure_part` / :meth:`ensure_source_part` / :meth:`set_part_thumb` are the
  worker-facing, idempotent region/thumbnail recorders (``@internal``).

Multi-statement writes run inside :meth:`Postgres.transaction` so a ``media`` row
and the ``document``/``document_part`` row that references it commit atomically.
The non-transactional S3 upload is always sequenced *before* the transaction;
because object keys are deterministic, a rolled-back transaction leaves at most a
harmless object reused verbatim on the next attempt.
"""

from collections.abc import Sequence
from uuid import UUID, uuid4

from opentelemetry.trace import SpanKind, get_current_span

from doci.documents.models import (
    DocumentListPage,
    DocumentPartRecord,
    DocumentRecord,
    DocumentStatus,
    PartKind,
    UploadIntent,
    page_locator,
)
from doci.helpers import internal
from doci.media import MediaConfig, MediaRecord, MediaService, Render
from doci.media import TooLarge, UnsupportedType  # noqa: F401  (re-exported for routers)
from doci.media import MediaView
from doci.postgres import Postgres
from doci.telemetry import traced, with_metrics, with_span

# document columns + the joined original-blob metadata (object_key/mime/size).
_DOC_SELECT = (
    "SELECT d.id, d.media_id, d.name, d.status, d.page_count, "
    "       d.deleted_at, d.purge_after, d.created_at, d.updated_at, "
    "       m.object_key, m.mime_type, m.size_bytes "
    "FROM document d JOIN media m ON m.id = d.media_id"
)
_PART_COLS = (
    "id, document_id, locator, kind, page_number, media_id, thumb_media_id, "
    "created_at, updated_at"
)


class DocumentError(Exception):
    """Base class for document-service errors."""


class DocumentNotFound(DocumentError):
    pass


class AlreadyFinalized(DocumentError):
    pass


@traced
class DocumentService:
    """The document domain over ``document`` / ``document_part`` + ``media`` blobs."""

    def __init__(
        self,
        *,
        postgres: Postgres,
        media: MediaService,
        config: MediaConfig,
    ) -> None:
        self._pg = postgres
        self._media = media
        self._cfg = config

    # region upload lifecycle (client-facing)
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def request_upload(self, *, name: str | None = None) -> UploadIntent:
        """Create a `new` document (+ its original blob row) and presign the PUT."""
        doc_id = uuid4()
        object_key = f"doc/{doc_id}/original"
        async with self._pg.transaction() as tx:
            media = await self._media.insert_blob(tx, object_key=object_key)
            await tx.execute(
                "INSERT INTO document (id, media_id, name, status) "
                "VALUES (%s, %s, %s, %s)",
                [doc_id, media.id, name, int(DocumentStatus.NEW)],
            )
        upload_url = await self._media.presign_put(object_key)
        return UploadIntent(id=doc_id, upload_url=upload_url)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def finalize(self, document_id: UUID) -> DocumentRecord:
        """Validate the uploaded original (MIME + size) and mark it ready/invalid."""
        _annotate(document_id)
        doc = await self._fetch(document_id)
        if doc.status is not DocumentStatus.NEW:
            raise AlreadyFinalized(str(document_id))
        try:
            mime, size = await self._media.validate_object(
                doc.object_key, name=doc.name
            )
        except TooLarge, UnsupportedType:
            await self._set_status(document_id, DocumentStatus.INVALID)
            raise
        async with self._pg.transaction() as tx:
            await tx.execute(
                "UPDATE media SET mime_type = %s, size_bytes = %s, updated_at = now() "
                "WHERE id = %s",
                [mime, size, doc.media_id],
            )
            await tx.execute(
                "UPDATE document SET status = %s, updated_at = now() WHERE id = %s",
                [int(DocumentStatus.READY), document_id],
            )
        return await self._fetch(document_id, include_deleted=True)

    # endregion

    # region regions + thumbnails (worker-facing, idempotent)
    @internal
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def ensure_part(
        self,
        document_id: UUID,
        *,
        locator: str,
        kind: PartKind,
        render: Render,
        page_number: int | None = None,
    ) -> DocumentPartRecord:
        """Idempotently materialize the region ``locator`` of ``document_id``.

        On a rerun the existing part is returned without rendering or touching S3.
        Otherwise ``render`` produces the bytes, they're stored at the deterministic
        key ``doc/{document_id}/{locator}``, and the ``media`` + ``document_part``
        rows commit together; ``ON CONFLICT (document_id, locator)`` is the race
        guard.
        """
        existing = await self._part_row_by_locator(document_id, locator)
        if existing is not None and existing["media_id"] is not None:
            return DocumentPartRecord.from_row(existing)

        data, mime = await render()
        object_key = f"doc/{document_id}/{locator}"
        await self._media.upload_object(object_key, data, mime)
        async with self._pg.transaction() as tx:
            media = await self._media.insert_blob(
                tx, object_key=object_key, mime=mime, size=len(data)
            )
            row = await tx.fetch_one(
                f"INSERT INTO document_part "
                f"(document_id, locator, kind, page_number, media_id) "
                f"VALUES (%s, %s, %s, %s, %s) "
                f"ON CONFLICT (document_id, locator) DO NOTHING "
                f"RETURNING {_PART_COLS}",
                [document_id, locator, int(kind), page_number, media.id],
            )
        if row is None:  # raced — another run won the insert; use the winner
            row = await self._part_row_by_locator(document_id, locator)
        return DocumentPartRecord.from_row(row)

    @internal
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def ensure_source_part(
        self, document_id: UUID, *, kind: PartKind
    ) -> DocumentPartRecord:
        """Register the original blob itself as the document's single page part.

        For inputs that are not split (a standalone image): the "page" is the file
        as uploaded, so the part points at ``document.media_id`` — no new blob and
        no S3 upload. Idempotent on ``(document_id, locator)``. Results and the
        thumbnail then key on this part, uniform with split PDF pages.
        """
        locator = page_locator(1)
        existing = await self._part_row_by_locator(document_id, locator)
        if existing is not None:
            return DocumentPartRecord.from_row(existing)
        doc = await self._fetch(document_id)
        row = await self._pg.fetch_one(
            f"INSERT INTO document_part "
            f"(document_id, locator, kind, page_number, media_id) "
            f"VALUES (%s, %s, %s, 1, %s) "
            f"ON CONFLICT (document_id, locator) DO NOTHING "
            f"RETURNING {_PART_COLS}",
            [document_id, locator, int(kind), doc.media_id],
        )
        if row is None:  # raced
            row = await self._part_row_by_locator(document_id, locator)
        return DocumentPartRecord.from_row(row)

    @internal
    async def set_part_thumb(self, part_id: UUID, thumb_media_id: UUID) -> None:
        """Record a region's thumbnail blob (idempotent: only sets if unset)."""
        await self._pg.execute(
            "UPDATE document_part SET thumb_media_id = %s, updated_at = now() "
            "WHERE id = %s AND thumb_media_id IS NULL",
            [thumb_media_id, part_id],
        )

    @internal
    async def set_page_count(self, document_id: UUID, page_count: int) -> None:
        """Record the document's total page count."""
        await self._pg.execute(
            "UPDATE document SET page_count = %s, updated_at = now() WHERE id = %s",
            [page_count, document_id],
        )

    # endregion

    # region reads
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get(self, document_id: UUID) -> DocumentRecord:
        """Fetch a (non-deleted) document by id."""
        _annotate(document_id)
        return await self._fetch(document_id)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def list_documents(
        self, *, limit: int | None = None, offset: int = 0
    ) -> DocumentListPage:
        """List documents (newest first), paginated."""
        lim = max(1, min(limit or self._cfg.page_size, self._cfg.max_page_size))
        offset = max(0, offset)
        rows = await self._pg.fetch_all(
            f"{_DOC_SELECT} WHERE d.deleted_at IS NULL "
            "ORDER BY d.created_at DESC, d.id LIMIT %s OFFSET %s",
            [lim + 1, offset],
        )
        has_more = len(rows) > lim
        items = [DocumentRecord.from_row(r) for r in rows[:lim]]
        return DocumentListPage(
            items=items, limit=lim, offset=offset, has_more=has_more
        )

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get_view(self, document_id: UUID) -> MediaView:
        """Presigned view URLs for the original + its page regions.

        Head is the original blob; children are the page parts. A standalone
        image's single part *is* the original (same blob), so it's excluded from
        the children to avoid showing the same blob twice.
        """
        _annotate(document_id)
        doc = await self._fetch(document_id)
        parts = await self._parts(document_id)
        page_ids = [
            p.media_id for p in parts if p.media_id and p.media_id != doc.media_id
        ]
        media_ids = [doc.media_id, *page_ids]
        by_id = await self._media.get_many(media_ids)
        records = [by_id[mid] for mid in media_ids if mid in by_id]
        return await self._view(records)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get_view_thumb(self, document_id: UUID) -> MediaView:
        """Presigned view URLs for each page region's thumbnail (head = first).

        Thumbnails are inherently per-region: a PDF yields one per page, a
        standalone image one for its single part. Raises if no thumbnail exists.
        """
        _annotate(document_id)
        parts = await self._parts(document_id)
        thumb_ids = [p.thumb_media_id for p in parts if p.thumb_media_id]
        by_id = await self._media.get_many(thumb_ids)
        records = [by_id[tid] for tid in thumb_ids if tid in by_id]
        if not records:
            raise DocumentNotFound(f"no thumbnail for {document_id}")
        return await self._view(records)

    # endregion

    # region deletion
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def delete(self, ids: Sequence[UUID]) -> int:
        """Soft-delete documents and route all their blobs into the purge window."""
        id_list = list(ids)
        if not id_list:
            return 0
        async with self._pg.transaction() as tx:
            await tx.execute(
                """
                WITH docs AS (
                    SELECT id, media_id FROM document
                    WHERE id = ANY(%(ids)s) AND deleted_at IS NULL
                ),
                blob_ids AS (
                    SELECT media_id AS id FROM docs WHERE media_id IS NOT NULL
                    UNION SELECT media_id FROM document_part
                        WHERE document_id IN (SELECT id FROM docs) AND media_id IS NOT NULL
                    UNION SELECT thumb_media_id FROM document_part
                        WHERE document_id IN (SELECT id FROM docs)
                          AND thumb_media_id IS NOT NULL
                )
                UPDATE media SET deleted_at = now(),
                                 purge_after = now() + %(purge)s * interval '1 second',
                                 updated_at = now()
                WHERE id IN (SELECT id FROM blob_ids) AND deleted_at IS NULL
                """,
                {"ids": id_list, "purge": self._cfg.purge_after},
            )
            rows = await tx.fetch_all(
                "UPDATE document SET deleted_at = now(), "
                "purge_after = now() + %(purge)s * interval '1 second', "
                "updated_at = now() "
                "WHERE id = ANY(%(ids)s) AND deleted_at IS NULL RETURNING id",
                {"ids": id_list, "purge": self._cfg.purge_after},
            )
        return len(rows)

    @internal
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def soft_delete_invalid(self) -> int:
        """Soft-delete all invalid documents (plus their blobs). Idempotent."""
        rows = await self._pg.fetch_all(
            "SELECT id FROM document WHERE status = %s AND deleted_at IS NULL",
            [int(DocumentStatus.INVALID)],
        )
        if not rows:
            return 0
        return await self.delete([r["id"] for r in rows])

    # endregion

    # region internals
    async def _fetch(
        self, document_id: UUID, *, include_deleted: bool = False
    ) -> DocumentRecord:
        query = f"{_DOC_SELECT} WHERE d.id = %s"
        if not include_deleted:
            query += " AND d.deleted_at IS NULL"
        row = await self._pg.fetch_one(query, [document_id])
        if row is None:
            raise DocumentNotFound(str(document_id))
        return DocumentRecord.from_row(row)

    async def _part_row_by_locator(self, document_id: UUID, locator: str):
        """Fetch the raw ``document_part`` row for ``(document_id, locator)``, or None.

        Shared by ``ensure_part`` / ``ensure_source_part`` for both the up-front
        idempotency check and the post-``ON CONFLICT`` race fallback, so the lookup
        lives in one place.
        """
        return await self._pg.fetch_one(
            f"SELECT {_PART_COLS} FROM document_part "
            "WHERE document_id = %s AND locator = %s",
            [document_id, locator],
        )

    async def _parts(self, document_id: UUID) -> list[DocumentPartRecord]:
        rows = await self._pg.fetch_all(
            f"SELECT {_PART_COLS} FROM document_part WHERE document_id = %s "
            "ORDER BY page_number NULLS LAST, locator",
            [document_id],
        )
        return [DocumentPartRecord.from_row(r) for r in rows]

    async def _set_status(self, document_id: UUID, status: DocumentStatus) -> None:
        await self._pg.execute(
            "UPDATE document SET status = %s, updated_at = now() WHERE id = %s",
            [int(status), document_id],
        )

    async def _view(self, records: list[MediaRecord]) -> MediaView:
        urls = await self._media.view_urls([r.object_key for r in records])
        views = [
            MediaView(media=r, view_url=u) for r, u in zip(records, urls, strict=True)
        ]
        return MediaView(
            media=views[0].media, view_url=views[0].view_url, children=views[1:]
        )

    # endregion


def _annotate(document_id: UUID) -> None:
    get_current_span().set_attribute("document.id", str(document_id))
