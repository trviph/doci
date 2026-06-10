-- Re-key workflow_result on the document region it describes rather than the raw
-- blob: results belong to a `document_part` (a PDF page, or an image's single
-- self-part). Also drop `document.thumb_media_id` — every processed unit is now a
-- part, so thumbnails live uniformly on `document_part.thumb_media_id`. Clean
-- cutover — no result data to migrate.
ALTER TABLE workflow_result DROP COLUMN media_id CASCADE;  -- drops the media unique + index

ALTER TABLE workflow_result
    ADD COLUMN part_id UUID NOT NULL REFERENCES document_part(id) ON DELETE CASCADE;

ALTER TABLE workflow_result
    ADD CONSTRAINT workflow_result_execution_part_kind_key
    UNIQUE (execution_id, part_id, kind);

CREATE INDEX idx_workflow_result_part ON workflow_result (part_id, kind);

ALTER TABLE document DROP COLUMN thumb_media_id;
