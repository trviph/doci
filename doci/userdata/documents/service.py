"""Document-definition service: documents expected within a dossier (m‑1).

Owns ``document_def``. Keyed by the parent ``dossier_key`` (resolved to the
dossier id directly, like the legacy group-items path). Upserts are idempotent on
``(dossier_id, key)``; a provided ``key`` updates the existing document, an
omitted one derives a fresh slug.
"""

from opentelemetry.trace import SpanKind
from psycopg2.extras import register_uuid

from doci.postgres import Postgres
from doci.telemetry import traced, with_metrics, with_span
from doci.userdata.common import gen_key
from doci.userdata.documents.models import DocumentDef
from doci.userdata.errors import NotFound

register_uuid()

_COLS = "id, dossier_id, key, name, description, look_for, created_at, updated_at"


@traced
class DocumentDefService:
    """The document-definition domain over ``document_def``."""

    def __init__(self, *, postgres: Postgres) -> None:
        self._pg = postgres

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def list_documents(self, dossier_key: str) -> list[DocumentDef]:
        """List one dossier's document definitions (newest first)."""
        dossier_id = await self._dossier_id(dossier_key)
        rows = await self._pg.fetch_all(
            f"SELECT {_COLS} FROM document_def WHERE dossier_id = %s "
            "ORDER BY created_at DESC, id",
            [dossier_id],
        )
        return [DocumentDef.from_row(r) for r in rows]

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get_document(self, dossier_key: str, doc_key: str) -> DocumentDef:
        """Fetch one document definition within a dossier."""
        dossier_id = await self._dossier_id(dossier_key)
        row = await self._pg.fetch_one(
            f"SELECT {_COLS} FROM document_def WHERE dossier_id = %s AND key = %s",
            [dossier_id, doc_key],
        )
        if row is None:
            raise NotFound(f"document_def {doc_key!r}")
        return DocumentDef.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def upsert_document(
        self,
        dossier_key: str,
        *,
        name: str,
        key: str | None = None,
        description: str | None = None,
        look_for: str | None = None,
    ) -> DocumentDef:
        """Create or update a document definition. Idempotent on ``(dossier, key)``."""
        dossier_id = await self._dossier_id(dossier_key)
        key = key or gen_key(name)
        row = await self._pg.fetch_one(
            "INSERT INTO document_def "
            "(dossier_id, key, name, description, look_for) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (dossier_id, key) DO UPDATE SET "
            "name = EXCLUDED.name, description = EXCLUDED.description, "
            "look_for = EXCLUDED.look_for, updated_at = now() "
            f"RETURNING {_COLS}",
            [dossier_id, key, name, description, look_for],
        )
        return DocumentDef.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def delete_document(self, dossier_key: str, doc_key: str) -> int:
        """Hard-delete one document definition (it carries no blobs). Returns rows removed."""
        dossier_id = await self._dossier_id(dossier_key)
        return await self._pg.execute(
            "DELETE FROM document_def WHERE dossier_id = %s AND key = %s",
            [dossier_id, doc_key],
        )

    # region private
    async def _dossier_id(self, dossier_key: str):
        row = await self._pg.fetch_one(
            "SELECT id FROM dossier_def WHERE key = %s AND deleted_at IS NULL",
            [dossier_key],
        )
        if row is None:
            raise NotFound(f"dossier_def {dossier_key!r}")
        return row["id"]

    # endregion
