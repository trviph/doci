-- Demote `media` to pure blob storage. The hierarchy (`parent_id`), the
-- type/lifecycle semantics (`type`, `status`), and the original's display
-- `name` now live in `document` / `document_part`. Clean cutover — no live
-- media data to migrate.
DROP INDEX IF EXISTS idx_media_parent_id;
DROP INDEX IF EXISTS idx_media_type;
DROP INDEX IF EXISTS idx_media_status_created_at;

ALTER TABLE media
    DROP COLUMN parent_id,
    DROP COLUMN type,
    DROP COLUMN status,
    DROP COLUMN name;
