-- A `document_part` is a derived region of a document: a page today
-- (locator 'p0001', 'p0002', ...), an arbitrary range later (e.g.
-- 'sheetA-r1c2:r100c2'). `locator` is the idempotency key — a given
-- (document_id, locator) maps to exactly one part, created once and uploaded
-- once. `media_id` is the rendered region blob; `thumb_media_id` its thumbnail.
CREATE TABLE document_part (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id    UUID         NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    locator        VARCHAR(255) NOT NULL,                      -- idempotency key within the document
    kind           SMALLINT     NOT NULL DEFAULT 0 CHECK (kind >= 0),  -- 0=text 1=image
    page_number    INT          CHECK (page_number >= 0),      -- ordering; null for non-page regions
    media_id       UUID         REFERENCES media(id) ON DELETE CASCADE,    -- region blob
    thumb_media_id UUID         REFERENCES media(id) ON DELETE SET NULL,   -- region thumbnail blob
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (document_id, locator)
);

CREATE INDEX idx_document_part_document_page ON document_part (document_id, page_number);
