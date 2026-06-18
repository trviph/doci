-- Drop the legacy userdata tables superseded by the v2 per-concern model:
--   document_group (+ document_group_item) → dossier_def (+ document_def)
--   audit_rule                             → agent_rule (+ agent_rule_dossier)
--
-- The mining pipeline now reads dossier_def/document_def; the legacy services,
-- router, and models have been removed. Reference datasets (reference_dataset /
-- reference_record) are NOT touched — they have no v2 replacement and stay live.

DROP TABLE IF EXISTS document_group_item;  -- FK child of document_group
DROP TABLE IF EXISTS document_group;
DROP TABLE IF EXISTS audit_rule;
