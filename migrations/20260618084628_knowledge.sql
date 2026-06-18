-- Replace the structured reference-data registry with a natural-language
-- "knowledge" table: org-provided reference material an agent consults
-- (authority matrix, vendor policy, …) as prose rather than typed rows.
--
-- Drops the legacy reference_dataset (+ reference_record) — no v2 keeps their
-- schema-on-read shape. Single-tenant; soft delete via `deleted_at`; key unique
-- is partial (WHERE deleted_at IS NULL) so a key can be reused after soft delete.

DROP TABLE IF EXISTS reference_record;  -- FK child of reference_dataset
DROP TABLE IF EXISTS reference_dataset;

CREATE TABLE knowledge (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    key         VARCHAR(255) NOT NULL,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    body        TEXT         NOT NULL,
    deleted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_knowledge_key        ON knowledge (key) WHERE deleted_at IS NULL;
CREATE INDEX        idx_knowledge_created_at ON knowledge (created_at DESC);
