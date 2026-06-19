-- Enable trigram similarity so knowledge search can rank entries by fuzzy
-- relevance (pg_trgm `word_similarity`) instead of a brittle whole-phrase
-- substring match: a multi-word query like "LOA matrix" should surface
-- "LOA / Authority matrix" by similarity, not require a contiguous substring.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
