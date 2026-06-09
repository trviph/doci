CREATE TABLE workflow_result (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID        NOT NULL REFERENCES workflow_execution(id) ON DELETE CASCADE,
    media_id     UUID        NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    kind         VARCHAR(32) NOT NULL,                              -- values enforced by the ResultKind StrEnum in code
    content      JSONB       NOT NULL,                              -- annotation object, or {"result": <text>} for text kinds
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (execution_id, media_id, kind)                          -- one result per (run, media, kind); enables idempotent upsert
);

CREATE INDEX idx_workflow_result_media     ON workflow_result (media_id, kind);
CREATE INDEX idx_workflow_result_execution ON workflow_result (execution_id);
CREATE INDEX idx_workflow_result_content   ON workflow_result USING gin (content);
