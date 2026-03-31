-- ============================================================
-- Docs Viewer  –  v1.83.12
-- Run this migration once on any existing deployment to add the
-- doc_page_visibility table and the 'Docs' nav item.
-- Safe to run multiple times (all statements are idempotent).
-- ============================================================

-- ── Table: per-filename department visibility ─────────────────
-- Empty table = all docs visible to all departments (open default).
-- Rows restrict a specific filename to listed departments only.
-- admin/superadmin always see all docs regardless.
CREATE TABLE IF NOT EXISTS doc_page_visibility (
    id          SERIAL PRIMARY KEY,
    filename    TEXT NOT NULL,
    dept_id     INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(filename, dept_id)
);

CREATE INDEX IF NOT EXISTS idx_dpv_filename ON doc_page_visibility(filename);
CREATE INDEX IF NOT EXISTS idx_dpv_dept     ON doc_page_visibility(dept_id);

-- ── Nav item: add Docs under the technical_tools group ────────
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT ng.id, 'docs', 'Docs', '📚', '/docs', 'docs', 3
FROM   nav_groups ng WHERE ng.key = 'technical_tools'
ON CONFLICT (key) DO NOTHING;

-- ── Dept nav item visibility: wire Docs into every department ─
-- that already has the technical_tools nav group enabled.
INSERT INTO department_nav_items (department_id, nav_item_id)
SELECT dng.department_id, ni.id
FROM   department_nav_groups dng
JOIN   nav_groups  ng  ON ng.id  = dng.nav_group_id AND ng.key = 'technical_tools'
JOIN   nav_items   ni  ON ni.key = 'docs'
ON CONFLICT DO NOTHING;
