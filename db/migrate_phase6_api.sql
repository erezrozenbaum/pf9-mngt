-- Phase 6: API Layer — Region Context on Endpoints (v1.75.0)
-- ============================================================
-- Adds region_id to search_documents for region-scoped full-text search,
-- and updates the search_ranked stored function to accept an optional
-- region filter parameter.
--
-- IDEMPOTENT: safe to run multiple times.
-- Guard in api/main.py startup checks search_documents.region_id exists.

-- Add region_id column to search_documents (nullable — existing docs unscoped)
ALTER TABLE search_documents
    ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);

CREATE INDEX IF NOT EXISTS idx_search_documents_region_id
    ON search_documents (region_id);

-- Update search_ranked function to support optional region_id filter.
-- Signature is backward-compatible: new filter_region parameter defaults to NULL
-- so existing callers (search_worker, indexer) continue to work without changes.
CREATE OR REPLACE FUNCTION public.search_ranked(
    query_text      text,
    filter_types    text[]           DEFAULT NULL::text[],
    filter_tenant   text             DEFAULT NULL::text,
    filter_domain   text             DEFAULT NULL::text,
    filter_from     timestamptz      DEFAULT NULL::timestamptz,
    filter_to       timestamptz      DEFAULT NULL::timestamptz,
    result_limit    integer          DEFAULT 50,
    result_offset   integer          DEFAULT 0,
    filter_region   text             DEFAULT NULL::text
)
RETURNS TABLE(
    doc_id          uuid,
    doc_type        text,
    tenant_id       text,
    tenant_name     text,
    domain_id       text,
    domain_name     text,
    resource_id     text,
    resource_name   text,
    title           text,
    ts              timestamptz,
    metadata        jsonb,
    rank            real,
    headline_title  text,
    headline_body   text
)
LANGUAGE plpgsql AS $function$
DECLARE
    tsq tsquery;
BEGIN
    tsq := websearch_to_tsquery('english', query_text);

    RETURN QUERY
    SELECT
        sd.doc_id,
        sd.doc_type,
        sd.tenant_id,
        sd.tenant_name,
        sd.domain_id,
        sd.domain_name,
        sd.resource_id,
        sd.resource_name,
        sd.title,
        sd.ts,
        sd.metadata,
        ts_rank_cd(sd.body_tsv, tsq, 32) AS rank,
        ts_headline('english', sd.title, tsq,
            'MaxFragments=1, MaxWords=20, MinWords=5, StartSel=<mark>, StopSel=</mark>'
        ) AS headline_title,
        ts_headline('english', sd.body_text, tsq,
            'MaxFragments=3, MaxWords=35, MinWords=10, StartSel=<mark>, StopSel=</mark>'
        ) AS headline_body
    FROM search_documents sd
    WHERE sd.body_tsv @@ tsq
      AND (filter_types  IS NULL OR sd.doc_type  = ANY(filter_types))
      AND (filter_tenant IS NULL OR sd.tenant_id = filter_tenant)
      AND (filter_domain IS NULL OR sd.domain_id = filter_domain)
      AND (filter_from   IS NULL OR sd.ts >= filter_from)
      AND (filter_to     IS NULL OR sd.ts <= filter_to)
      AND (filter_region IS NULL OR sd.region_id = filter_region)
    ORDER BY rank DESC, sd.ts DESC
    LIMIT result_limit
    OFFSET result_offset;
END;
$function$;
