-- Audit results: what the audit agent concludes for a dossier run.
--
--   audit_finding — one observation per rule/check: a status (pass / fail /
--     needs_review) + severity + a human message + evidence (page refs and the
--     verbatim facts.source quotes the finding rests on).
--   audit_verdict — the dossier-level conclusion for the run (pass / needs_review
--     / fail, §7), one per audit execution.
--
-- Both hang off the audit `workflow_execution` row (execution_id). Severity/status
-- are free-form VARCHAR (the agent fills them per the rule text) — documented
-- values: severity info|low|medium|high|critical|block; status pass|fail|needs_review.

CREATE TABLE audit_finding (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID         NOT NULL REFERENCES workflow_execution(id) ON DELETE CASCADE,
    rule_key     VARCHAR(255),
    severity     VARCHAR(32)  NOT NULL,
    status       VARCHAR(32)  NOT NULL,
    message      TEXT         NOT NULL,
    evidence     JSONB        NOT NULL DEFAULT '[]'::jsonb,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_finding_execution ON audit_finding (execution_id);

CREATE TABLE audit_verdict (
    execution_id UUID         PRIMARY KEY REFERENCES workflow_execution(id) ON DELETE CASCADE,
    dossier_key  VARCHAR(255),
    document_id  UUID         REFERENCES document(id) ON DELETE CASCADE,
    verdict      VARCHAR(32)  NOT NULL,
    rationale    TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
