-- ============================================================
-- Migration: Ops Assistant — Search & Similarity (v1 + v2)
-- Adds unified search_documents table with tsvector + pg_trgm
-- ============================================================

-- Enable trigram extension for similarity matching
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ── Unified search documents table ──────────────────────────
CREATE TABLE IF NOT EXISTS search_documents (
    doc_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_type        TEXT NOT NULL,         -- vm, volume, snapshot, alert, audit, event, drift, restore, backup, metering, etc.
    tenant_id       TEXT,                  -- project/tenant ID for RBAC filtering
    tenant_name     TEXT,
    domain_id       TEXT,
    domain_name     TEXT,
    resource_id     TEXT NOT NULL,         -- original resource ID
    resource_name   TEXT,                  -- display name
    title           TEXT NOT NULL,         -- short summary line
    body_text       TEXT NOT NULL DEFAULT '',  -- concatenated searchable text
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB DEFAULT '{}',   -- extra filterable attributes
    body_tsv        TSVECTOR,             -- full-text search vector (auto-maintained by trigger)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Indexes ─────────────────────────────────────────────────

-- Full-text search (BoW) — GIN index on tsvector
CREATE INDEX IF NOT EXISTS idx_search_documents_tsv
    ON search_documents USING GIN (body_tsv);

-- Trigram similarity on title (for "find similar" by title/error text)
CREATE INDEX IF NOT EXISTS idx_search_documents_title_trgm
    ON search_documents USING GIN (title gin_trgm_ops);

-- Trigram similarity on body_text (for "find similar" by full content)
CREATE INDEX IF NOT EXISTS idx_search_documents_body_trgm
    ON search_documents USING GIN (body_text gin_trgm_ops);

-- Lookup by resource
CREATE INDEX IF NOT EXISTS idx_search_documents_resource
    ON search_documents (doc_type, resource_id);

-- Tenant filtering
CREATE INDEX IF NOT EXISTS idx_search_documents_tenant
    ON search_documents (tenant_id);

-- Domain filtering
CREATE INDEX IF NOT EXISTS idx_search_documents_domain
    ON search_documents (domain_id);

-- Timestamp range queries
CREATE INDEX IF NOT EXISTS idx_search_documents_ts
    ON search_documents (ts DESC);

-- Type filtering
CREATE INDEX IF NOT EXISTS idx_search_documents_type
    ON search_documents (doc_type);

-- ── Auto-update tsvector trigger ────────────────────────────

CREATE OR REPLACE FUNCTION search_documents_tsv_trigger()
RETURNS TRIGGER AS $$
BEGIN
    NEW.body_tsv := setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A')
                 || setweight(to_tsvector('english', COALESCE(NEW.resource_name, '')), 'B')
                 || setweight(to_tsvector('english', COALESCE(NEW.body_text, '')), 'C');
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_search_documents_tsv ON search_documents;
CREATE TRIGGER trg_search_documents_tsv
    BEFORE INSERT OR UPDATE ON search_documents
    FOR EACH ROW
    EXECUTE FUNCTION search_documents_tsv_trigger();

-- ── Upsert-friendly unique constraint ───────────────────────
-- Allows indexer to do INSERT ... ON CONFLICT UPDATE
CREATE UNIQUE INDEX IF NOT EXISTS idx_search_documents_upsert
    ON search_documents (doc_type, resource_id, ts);

-- ── Indexer state tracking ──────────────────────────────────
CREATE TABLE IF NOT EXISTS search_indexer_state (
    doc_type        TEXT PRIMARY KEY,
    last_indexed_at TIMESTAMPTZ NOT NULL DEFAULT '1970-01-01T00:00:00Z',
    docs_count      INTEGER NOT NULL DEFAULT 0,
    last_run_at     TIMESTAMPTZ,
    last_run_duration_ms INTEGER
);

-- Seed initial state for each doc type
INSERT INTO search_indexer_state (doc_type) VALUES
    ('vm'), ('volume'), ('snapshot'), ('hypervisor'),
    ('network'), ('subnet'), ('router'), ('floating_ip'), ('port'),
    ('image'), ('flavor'), ('user'), ('security_group'),
    ('audit'), ('activity'), ('drift_event'),
    ('snapshot_run'), ('snapshot_record'),
    ('restore_job'), ('backup'),
    ('notification'), ('provisioning'),
    ('deletion')
ON CONFLICT (doc_type) DO NOTHING;

-- ── Helper function: ranked search ──────────────────────────
CREATE OR REPLACE FUNCTION search_ranked(
    query_text TEXT,
    filter_types TEXT[] DEFAULT NULL,
    filter_tenant TEXT DEFAULT NULL,
    filter_domain TEXT DEFAULT NULL,
    filter_from TIMESTAMPTZ DEFAULT NULL,
    filter_to TIMESTAMPTZ DEFAULT NULL,
    result_limit INTEGER DEFAULT 50,
    result_offset INTEGER DEFAULT 0
)
RETURNS TABLE (
    doc_id UUID,
    doc_type TEXT,
    tenant_id TEXT,
    tenant_name TEXT,
    domain_id TEXT,
    domain_name TEXT,
    resource_id TEXT,
    resource_name TEXT,
    title TEXT,
    ts TIMESTAMPTZ,
    metadata JSONB,
    rank REAL,
    headline_title TEXT,
    headline_body TEXT
) AS $$
DECLARE
    tsq tsquery;
BEGIN
    -- Build tsquery from plain text (handles multi-word, prefix matching)
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
      AND (filter_types IS NULL OR sd.doc_type = ANY(filter_types))
      AND (filter_tenant IS NULL OR sd.tenant_id = filter_tenant)
      AND (filter_domain IS NULL OR sd.domain_id = filter_domain)
      AND (filter_from IS NULL OR sd.ts >= filter_from)
      AND (filter_to IS NULL OR sd.ts <= filter_to)
    ORDER BY rank DESC, sd.ts DESC
    LIMIT result_limit
    OFFSET result_offset;
END;
$$ LANGUAGE plpgsql;

-- ── Helper function: find similar documents ─────────────────
CREATE OR REPLACE FUNCTION search_similar(
    target_doc_id UUID,
    similarity_threshold REAL DEFAULT 0.15,
    result_limit INTEGER DEFAULT 20
)
RETURNS TABLE (
    doc_id UUID,
    doc_type TEXT,
    tenant_id TEXT,
    tenant_name TEXT,
    domain_id TEXT,
    domain_name TEXT,
    resource_id TEXT,
    resource_name TEXT,
    title TEXT,
    ts TIMESTAMPTZ,
    metadata JSONB,
    title_similarity REAL,
    body_similarity REAL,
    combined_score REAL
) AS $$
DECLARE
    target_title TEXT;
    target_body TEXT;
BEGIN
    SELECT sd.title, sd.body_text INTO target_title, target_body
    FROM search_documents sd WHERE sd.doc_id = target_doc_id;

    IF target_title IS NULL THEN
        RAISE EXCEPTION 'Document not found: %', target_doc_id;
    END IF;

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
        similarity(sd.title, target_title) AS title_similarity,
        similarity(sd.body_text, target_body) AS body_similarity,
        (similarity(sd.title, target_title) * 0.6 + similarity(sd.body_text, target_body) * 0.4) AS combined_score
    FROM search_documents sd
    WHERE sd.doc_id != target_doc_id
      AND (
          similarity(sd.title, target_title) >= similarity_threshold
          OR similarity(sd.body_text, target_body) >= similarity_threshold
      )
    ORDER BY combined_score DESC
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql;

-- ── RBAC: grant search permissions to all roles ─────────────
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',     'search', 'read'),
    ('operator',   'search', 'read'),
    ('admin',      'search', 'admin'),
    ('superadmin', 'search', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;
