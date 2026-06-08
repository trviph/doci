CREATE TABLE workflow_execution (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow    VARCHAR(32) NOT NULL,                              -- which workflow ran: 'document_mining' | 'image'
    entity_type VARCHAR(32) NOT NULL,                              -- kind of object this run is about: 'media'
    entity_id   UUID        NOT NULL,                              -- that object's id (e.g. the media id)
    status      SMALLINT    NOT NULL DEFAULT 0 CHECK (status >= 0),-- 0=queued 1=running 2=succeeded 3=failed
    input       JSONB       NOT NULL,                              -- WorkflowInput (versioned): request snapshot
    result      JSONB,                                             -- WorkflowResult (versioned): output OR error
    metadata    JSONB       NOT NULL DEFAULT '{}'::jsonb,          -- WorkflowMetadata (versioned): {taskiq, langgraph, retry_count}
    started_at  TIMESTAMPTZ,                                       -- set when the worker begins
    finished_at TIMESTAMPTZ,                                       -- set on success/failure
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_workflow_execution_status_created_at ON workflow_execution (status, created_at DESC);
CREATE INDEX idx_workflow_execution_entity            ON workflow_execution (entity_type, entity_id);
