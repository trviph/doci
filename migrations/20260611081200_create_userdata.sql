-- User data layer: user/org-provided reference data that feeds the mining
-- pipelines and (later) an audit agent. Three concerns:
--
--   1. document_group (+ document_group_item) — first-class dossier definitions:
--      "a marketing payment request contains a VAT invoice, a PO, ..." Each item
--      carries the facts/features to look for (FieldSpec list) that the annotate
--      step extracts.
--   2. audit_rule — first-class audit rules with a structured envelope and a
--      tagged-union `check` body (prompt | expr).
--   3. reference_dataset (+ reference_record) — a unified, schema-on-read registry
--      for the long tail of org data (authority matrix, approved vendors, ...),
--      with one discover + query interface over all datasets.
--
-- Single-tenant (no owner/org column), matching `document` / `media`. Soft delete
-- via `deleted_at`; no `purge_after` (these rows own no S3 blobs to purge).

-- region document groups -----------------------------------------------------

-- A dossier type, e.g. 'payment_request_marketing'. `key` is the stable slug
-- callers reference (workflow input, audit-rule selectors).
CREATE TABLE document_group (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    key         VARCHAR(255) NOT NULL UNIQUE,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    deleted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_document_group_created_at ON document_group (created_at DESC);

-- One expected document within a group, e.g. 'vat_invoice'. `fields` is a JSON
-- list of FieldSpec ({name, hint}) — the facts/features to look for, fed to the
-- annotate step. `(group_id, key)` is the idempotency key for upserts.
CREATE TABLE document_group_item (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id    UUID         NOT NULL REFERENCES document_group(id) ON DELETE CASCADE,
    key         VARCHAR(255) NOT NULL,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    fields      JSONB        NOT NULL DEFAULT '[]'::jsonb,  -- [{name, hint}]
    required    BOOLEAN      NOT NULL DEFAULT true,
    sort_order  INT          NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (group_id, key)
);

CREATE INDEX idx_document_group_item_group ON document_group_item (group_id, sort_order);

-- endregion

-- region audit rules ---------------------------------------------------------

-- An audit rule. The envelope (name/applies_to/references/severity/enabled) is
-- always structured; the `check` body is a tagged union on its "type":
--   {"type": "prompt", "prompt": "..."}                  -- LLM-judged (v1 live path)
--   {"type": "expr",   "expr": "a.total == b.total"}     -- deterministic (evaluator deferred)
-- `applies_to` is a JSON list of selectors, e.g.
--   [{"group": "payment_request_marketing"}, {"document": "vat_invoice"}]   ([] = global).
-- `reference_keys` lists the facts/datasets to gather before evaluating, e.g.
--   ["vat_invoice.total_amount", "approved_vendors"].
-- (Columns avoid the reserved words `check` / `references` so queries need no quoting.)
CREATE TABLE audit_rule (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    key            VARCHAR(255) NOT NULL UNIQUE,
    name           VARCHAR(255) NOT NULL,
    description    TEXT,
    applies_to     JSONB        NOT NULL DEFAULT '[]'::jsonb,
    reference_keys JSONB        NOT NULL DEFAULT '[]'::jsonb,
    check_body     JSONB        NOT NULL,
    severity       SMALLINT     NOT NULL DEFAULT 0 CHECK (severity >= 0),  -- 0=info 1=warn 2=block
    enabled        BOOLEAN      NOT NULL DEFAULT true,
    deleted_at     TIMESTAMPTZ,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_rule_enabled    ON audit_rule (enabled) WHERE deleted_at IS NULL;
CREATE INDEX idx_audit_rule_applies_to ON audit_rule USING gin (applies_to);

-- endregion

-- region reference datasets (unified registry) -------------------------------

-- The catalog of unified reference datasets, e.g. 'authority_matrix',
-- 'approved_vendors'. `field_schema` declares the row shape:
--   [{"name": "role", "type": "string", "description": "...", "required": true}, ...]
-- and powers both discovery (agents learn the columns) and query validation.
CREATE TABLE reference_dataset (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    key          VARCHAR(255) NOT NULL UNIQUE,
    name         VARCHAR(255) NOT NULL,
    description  TEXT,
    field_schema JSONB        NOT NULL DEFAULT '[]'::jsonb,
    deleted_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_reference_dataset_created_at ON reference_dataset (created_at DESC);

-- A row within a dataset. `data` conforms to the dataset's `field_schema`.
-- `key` is an optional natural key for idempotent upsert; the GIN index on
-- `data` powers `@>` containment (equality) filters in the uniform query API.
CREATE TABLE reference_record (
    id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id UUID         NOT NULL REFERENCES reference_dataset(id) ON DELETE CASCADE,
    key        VARCHAR(255),
    data       JSONB        NOT NULL DEFAULT '{}'::jsonb,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, key)
);

CREATE INDEX idx_reference_record_dataset ON reference_record (dataset_id);
CREATE INDEX idx_reference_record_data    ON reference_record USING gin (data);

-- endregion
