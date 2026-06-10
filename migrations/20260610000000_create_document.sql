-- A `document` is the original uploaded file as a domain entity. It owns the
-- upload/validation lifecycle (`status`, moved off `media`) and points at the
-- original blob plus an optional thumbnail of that original. Derived pages live
-- in `document_part` (next migration). `media` is pure blob storage.
CREATE TABLE document (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    media_id       UUID         NOT NULL UNIQUE REFERENCES media(id) ON DELETE CASCADE,  -- original blob
    thumb_media_id UUID         REFERENCES media(id) ON DELETE SET NULL,                 -- thumb of the original
    name           VARCHAR(255),
    status         SMALLINT     NOT NULL DEFAULT 0 CHECK (status >= 0),  -- 0=new 1=ready 2=invalid
    page_count     INT          CHECK (page_count >= 0),
    deleted_at     TIMESTAMPTZ,
    purge_after    TIMESTAMPTZ,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_document_status_created_at ON document (status, created_at DESC);
CREATE INDEX idx_document_purge_after ON document (purge_after) WHERE purge_after IS NOT NULL;
