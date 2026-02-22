-- =====================================================================
-- Migration: Ops Copilot tables
-- Adds conversation history, feedback tracking, and configuration
-- for the three-tier Ops Copilot (built-in / Ollama / external LLM).
-- =====================================================================

-- 1. Conversation history --------------------------------------------------
CREATE TABLE IF NOT EXISTS copilot_history (
    id                  SERIAL PRIMARY KEY,
    username            TEXT        NOT NULL,
    question            TEXT        NOT NULL,
    answer              TEXT        NOT NULL,
    intent              TEXT,                          -- matched intent key (NULL for LLM-only answers)
    backend_used        TEXT        NOT NULL DEFAULT 'builtin',  -- builtin | ollama | openai | anthropic
    confidence          REAL,                          -- 0.0–1.0 for intent engine; NULL for LLM
    data_sent_external  BOOLEAN     NOT NULL DEFAULT FALSE,
    tokens_used         INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_copilot_history_user     ON copilot_history (username);
CREATE INDEX IF NOT EXISTS idx_copilot_history_created  ON copilot_history (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_copilot_history_backend  ON copilot_history (backend_used);

-- 2. Feedback on answers ---------------------------------------------------
CREATE TABLE IF NOT EXISTS copilot_feedback (
    id              SERIAL PRIMARY KEY,
    history_id      INTEGER     NOT NULL REFERENCES copilot_history(id) ON DELETE CASCADE,
    helpful         BOOLEAN     NOT NULL,
    comment         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_copilot_feedback_history ON copilot_feedback (history_id);

-- 3. Singleton configuration row -------------------------------------------
CREATE TABLE IF NOT EXISTS copilot_config (
    id                      INTEGER     PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    backend                 TEXT        NOT NULL DEFAULT 'builtin',   -- builtin | ollama | openai | anthropic
    ollama_url              TEXT        NOT NULL DEFAULT 'http://localhost:11434',
    ollama_model            TEXT        NOT NULL DEFAULT 'llama3',
    openai_api_key          TEXT        NOT NULL DEFAULT '',
    openai_model            TEXT        NOT NULL DEFAULT 'gpt-4o-mini',
    anthropic_api_key       TEXT        NOT NULL DEFAULT '',
    anthropic_model         TEXT        NOT NULL DEFAULT 'claude-sonnet-4-20250514',
    redact_sensitive        BOOLEAN     NOT NULL DEFAULT TRUE,
    max_history_per_user    INTEGER     NOT NULL DEFAULT 200,
    system_prompt           TEXT        NOT NULL DEFAULT 'You are Ops Copilot, an AI assistant for Platform9 infrastructure management. Answer concisely using the provided infrastructure context. If you are unsure, say so.',
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by              TEXT
);

INSERT INTO copilot_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- 4. RBAC permissions for Copilot ------------------------------------------
-- All roles get read access (can ask questions & see suggestions).
-- Admin / superadmin get write+admin (can change backend config, test connections).
INSERT INTO role_permissions (role, resource, action) VALUES
('viewer',     'copilot', 'read'),
('operator',   'copilot', 'read'),
('technical',  'copilot', 'read'),
('admin',      'copilot', 'read'),
('admin',      'copilot', 'write'),
('admin',      'copilot', 'admin'),
('superadmin', 'copilot', 'read'),
('superadmin', 'copilot', 'write'),
('superadmin', 'copilot', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;
