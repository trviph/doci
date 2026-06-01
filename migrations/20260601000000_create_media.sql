CREATE TYPE media_type AS ENUM ('original', 'thumb', 'page');

CREATE TABLE media (
    id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id   UUID          REFERENCES media(id) ON DELETE CASCADE,
    type        media_type    NOT NULL DEFAULT 'original',
    object_key  VARCHAR(1024) NOT NULL UNIQUE,
    name        VARCHAR(255),
    mime_type   VARCHAR(127),
    size_bytes  BIGINT        CHECK (size_bytes >= 0),
    status      SMALLINT      NOT NULL DEFAULT 0 CHECK (status >= 0),
    deleted_at  TIMESTAMPTZ,
    purge_after TIMESTAMPTZ,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX idx_media_parent_id ON media (parent_id) WHERE parent_id IS NOT NULL;
CREATE INDEX idx_media_type ON media (type);
CREATE INDEX idx_media_status_created_at ON media (status, created_at DESC);
CREATE INDEX idx_media_purge_after ON media (purge_after) WHERE purge_after IS NOT NULL;
