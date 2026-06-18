-- User data layer, v2: a simplified, per-concern split of the dossier/document/
-- rule shapes (reference datasets are unchanged, see the v1 migration). Four
-- plaintext concerns:
--
--   1. dossier_def — a named case-file type ("payment request", "marketing", ...),
--      just a name + free-text description.
--   2. document_def — one kind of document expected within a dossier (m-1), with
--      an optional plaintext `look_for` note on what to look for.
--   3. agent_rule — a named, markdown rule body. Generic ("agent rule", not
--      "audit rule") since rules other than audit may run.
--   4. agent_rule_dossier — the m-n link: a rule runs on many dossiers, a dossier
--      has many rules.
--
-- Single-tenant (no owner/org column), matching `document` / `media`. Soft delete
-- via `deleted_at`; unique on `key` is partial (WHERE deleted_at IS NULL) so a key
-- can be reused after soft delete. These rows own no S3 blobs.
--
-- Built alongside the legacy v1 userdata tables (document_group / audit_rule /
-- reference_dataset), which stay live until the mining pipeline is migrated.

-- region dossier definitions -------------------------------------------------

CREATE TABLE dossier_def (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    key         VARCHAR(255) NOT NULL,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    deleted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_dossier_def_key        ON dossier_def (key) WHERE deleted_at IS NULL;
CREATE INDEX        idx_dossier_def_created_at ON dossier_def (created_at DESC);

-- endregion

-- region document definitions ------------------------------------------------

-- One expected document within a dossier (m-1). `look_for` is an optional
-- free-text note on what to look for. `(dossier_id, key)` is the upsert key.
CREATE TABLE document_def (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    dossier_id  UUID         NOT NULL REFERENCES dossier_def(id) ON DELETE CASCADE,
    key         VARCHAR(255) NOT NULL,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    look_for    TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (dossier_id, key)
);

CREATE INDEX idx_document_def_dossier ON document_def (dossier_id, created_at DESC);

-- endregion

-- region agent rules ---------------------------------------------------------

-- A named, markdown rule body an agent applies to its linked dossiers.
CREATE TABLE agent_rule (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    key         VARCHAR(255) NOT NULL,
    name        VARCHAR(255) NOT NULL,
    body        TEXT         NOT NULL,
    deleted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_agent_rule_key        ON agent_rule (key) WHERE deleted_at IS NULL;
CREATE INDEX        idx_agent_rule_created_at ON agent_rule (created_at DESC);

-- The m-n link between rules and dossiers. Both sides cascade on hard delete.
CREATE TABLE agent_rule_dossier (
    rule_id    UUID NOT NULL REFERENCES agent_rule(id)  ON DELETE CASCADE,
    dossier_id UUID NOT NULL REFERENCES dossier_def(id) ON DELETE CASCADE,
    PRIMARY KEY (rule_id, dossier_id)
);

CREATE INDEX idx_agent_rule_dossier_dossier ON agent_rule_dossier (dossier_id);

-- endregion
