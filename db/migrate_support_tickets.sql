-- =============================================================================
-- Phase T1: Support Ticket System — Tables, SLA Policies, Email Templates
-- Version: v1.58.0
-- =============================================================================
-- Idempotent: all guarded by IF NOT EXISTS / ON CONFLICT DO NOTHING.

-- ---------------------------------------------------------------------------
-- Ticket sequence (human-readable refs: TKT-2026-00001)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ticket_sequence (
    year     INT PRIMARY KEY,
    last_seq INT NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- Core tickets table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS support_tickets (
    id                    BIGSERIAL PRIMARY KEY,
    ticket_ref            TEXT UNIQUE NOT NULL,        -- TKT-YYYY-NNNNN

    title                 TEXT NOT NULL,
    description           TEXT NOT NULL DEFAULT '',

    ticket_type           TEXT NOT NULL DEFAULT 'service_request',
    -- service_request | incident | change_request | inquiry | escalation |
    -- auto_incident   | auto_change_request

    status                TEXT NOT NULL DEFAULT 'open',
    -- open | assigned | in_progress | waiting_customer | pending_approval |
    -- resolved | closed

    priority              TEXT NOT NULL DEFAULT 'normal',
    -- low | normal | high | critical

    -- Routing
    from_dept_id          INTEGER REFERENCES departments(id),
    to_dept_id            INTEGER NOT NULL REFERENCES departments(id),
    assigned_to           TEXT,

    -- Who opened it
    opened_by             TEXT NOT NULL,

    -- External customer (NOT a system user)
    customer_name         TEXT,
    customer_email        TEXT,
    auto_notify_customer  BOOLEAN NOT NULL DEFAULT false,

    -- OpenStack resource linkage (all optional)
    resource_type         TEXT,
    resource_id           TEXT,
    resource_name         TEXT,
    project_id            TEXT,
    project_name          TEXT,
    domain_id             TEXT,
    domain_name           TEXT,

    -- Auto-ticket metadata
    auto_source           TEXT,    -- drift | health_score | delete_impact | runbook_failure | migration
    auto_source_id        TEXT,
    auto_blocked          BOOLEAN NOT NULL DEFAULT false,

    -- Linked jobs (no FK — eventual consistency)
    linked_execution_id   TEXT,
    linked_job_id         TEXT,
    linked_migration_id   TEXT,

    -- Approval gate
    requires_approval     BOOLEAN NOT NULL DEFAULT false,
    approved_by           TEXT,
    approved_at           TIMESTAMPTZ,
    rejected_by           TEXT,
    rejected_at           TIMESTAMPTZ,
    approval_note         TEXT,

    -- SLA
    sla_response_hours    INTEGER,
    sla_resolve_hours     INTEGER,
    sla_response_at       TIMESTAMPTZ,
    sla_resolve_at        TIMESTAMPTZ,
    sla_response_breached BOOLEAN NOT NULL DEFAULT false,
    sla_resolve_breached  BOOLEAN NOT NULL DEFAULT false,
    first_response_at     TIMESTAMPTZ,

    -- Resolution
    resolved_by           TEXT,
    resolved_at           TIMESTAMPTZ,
    resolution_note       TEXT,

    -- Outbound email tracking
    customer_notified_at  TIMESTAMPTZ,
    last_email_subject    TEXT,

    -- Slack thread
    slack_ts              TEXT,
    slack_channel         TEXT,

    -- Escalation chain
    escalation_count      INTEGER NOT NULL DEFAULT 0,
    prev_dept_id          INTEGER REFERENCES departments(id),

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at             TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tickets_status       ON support_tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_to_dept      ON support_tickets(to_dept_id);
CREATE INDEX IF NOT EXISTS idx_tickets_opened_by    ON support_tickets(opened_by);
CREATE INDEX IF NOT EXISTS idx_tickets_assigned_to  ON support_tickets(assigned_to);
CREATE INDEX IF NOT EXISTS idx_tickets_created_at   ON support_tickets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tickets_ticket_ref   ON support_tickets(ticket_ref);
CREATE INDEX IF NOT EXISTS idx_tickets_auto_source  ON support_tickets(auto_source, auto_source_id);
CREATE INDEX IF NOT EXISTS idx_tickets_project_id   ON support_tickets(project_id);

-- ---------------------------------------------------------------------------
-- Comments / activity thread
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ticket_comments (
    id           BIGSERIAL PRIMARY KEY,
    ticket_id    BIGINT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
    author       TEXT NOT NULL,
    body         TEXT NOT NULL,
    is_internal  BOOLEAN NOT NULL DEFAULT false,
    comment_type TEXT NOT NULL DEFAULT 'comment',
    -- comment | status_change | assignment | escalation | runbook_result |
    -- approval | rejection | email_sent | auto_created | sla_breach | system
    metadata     JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ticket_comments_ticket_id  ON ticket_comments(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ticket_comments_created_at ON ticket_comments(created_at);

-- ---------------------------------------------------------------------------
-- SLA policies (per dept × ticket_type × priority)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ticket_sla_policies (
    id                       SERIAL PRIMARY KEY,
    to_dept_id               INTEGER NOT NULL REFERENCES departments(id),
    ticket_type              TEXT NOT NULL DEFAULT 'incident',
    priority                 TEXT NOT NULL DEFAULT 'normal',
    response_sla_hours       INTEGER NOT NULL DEFAULT 24,
    resolution_sla_hours     INTEGER NOT NULL DEFAULT 72,
    auto_escalate_on_breach  BOOLEAN NOT NULL DEFAULT false,
    escalate_to_dept_id      INTEGER REFERENCES departments(id),
    UNIQUE(to_dept_id, ticket_type, priority)
);

-- ---------------------------------------------------------------------------
-- Email templates
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ticket_email_templates (
    id            SERIAL PRIMARY KEY,
    template_name TEXT UNIQUE NOT NULL,
    subject       TEXT NOT NULL,
    html_body     TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- RBAC permissions for tickets resource
-- ---------------------------------------------------------------------------
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',     'tickets', 'read'),
    ('viewer',     'tickets', 'write'),
    ('operator',   'tickets', 'read'),
    ('operator',   'tickets', 'write'),
    ('admin',      'tickets', 'admin'),
    ('superadmin', 'tickets', 'admin'),
    ('technical',  'tickets', 'read'),
    ('technical',  'tickets', 'write')
ON CONFLICT (role, resource, action) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Navigation: "Operations & Support" group + items
-- ---------------------------------------------------------------------------
INSERT INTO nav_groups (key, label, icon, description, sort_order)
VALUES ('operations', 'Operations & Support', '🎫', 'Support tickets, incident management, and escalations', 9)
ON CONFLICT (key) DO UPDATE SET sort_order=9 WHERE nav_groups.key='operations';

INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
VALUES
    ((SELECT id FROM nav_groups WHERE key = 'operations'), 'tickets',  'Support Tickets', '🎫', '/tickets',  'tickets', 1),
    ((SELECT id FROM nav_groups WHERE key = 'operations'), 'my_queue', 'My Queue',        '📥', '/my_queue', 'tickets', 2)
ON CONFLICT (key) DO NOTHING;

-- Grant Operations & Support group + items visibility to all departments
INSERT INTO department_nav_groups (department_id, nav_group_id)
SELECT d.id, (SELECT id FROM nav_groups WHERE key = 'operations')
FROM departments d
ON CONFLICT DO NOTHING;

INSERT INTO department_nav_items (department_id, nav_item_id)
SELECT d.id, ni.id
FROM departments d, nav_items ni
WHERE ni.key IN ('tickets', 'my_queue')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Seed SLA policies
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    d_t1   INTEGER := (SELECT id FROM departments WHERE name = 'Tier1 Support' LIMIT 1);
    d_t2   INTEGER := (SELECT id FROM departments WHERE name = 'Tier2 Support' LIMIT 1);
    d_t3   INTEGER := (SELECT id FROM departments WHERE name = 'Tier3 Support' LIMIT 1);
    d_eng  INTEGER := (SELECT id FROM departments WHERE name = 'Engineering'   LIMIT 1);
    d_mgmt INTEGER := (SELECT id FROM departments WHERE name = 'Management'    LIMIT 1);
BEGIN
    -- Tier1: incident critical  (1h response / 4h resolve, auto-escalate to Tier2)
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t1, 'incident', 'critical', 1, 4, true, d_t2)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;

    -- Tier1: incident high  (4h response / 8h resolve, auto-escalate to Tier2)
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t1, 'incident', 'high', 4, 8, true, d_t2)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;

    -- Tier1: incident normal  (8h response / 24h resolve)
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_t1, 'incident', 'normal', 8, 24)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;

    -- Tier1: service_request normal  (8h response / 48h resolve)
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_t1, 'service_request', 'normal', 8, 48)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;

    -- Tier2: incident critical  (2h / 6h, auto-escalate to Engineering)
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t2, 'incident', 'critical', 2, 6, true, d_eng)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;

    -- Tier2: escalation (any priority) → 4h response / 24h resolve, auto-escalate to Engineering
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t2, 'escalation', 'critical', 4, 24, true, d_eng)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t2, 'escalation', 'high', 4, 24, true, d_eng)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t2, 'escalation', 'normal', 4, 24, true, d_eng)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t2, 'escalation', 'low', 4, 24, true, d_eng)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;

    -- Tier3: incident critical  (1h / 4h, auto-escalate to Engineering)
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t3, 'incident', 'critical', 1, 4, true, d_eng)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;

    -- Engineering: change_request high  (8h / 24h)
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_eng, 'change_request', 'high', 8, 24)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;

    -- Engineering: auto_change_request high  (4h / 16h)
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_eng, 'auto_change_request', 'high', 4, 16)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;

    -- Engineering: auto_incident critical  (2h / 8h)
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_eng, 'auto_incident', 'critical', 2, 8)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;

    -- Management: change_request all priorities  (24h / 72h)
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_mgmt, 'change_request', 'critical', 24, 72)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_mgmt, 'change_request', 'high', 24, 72)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_mgmt, 'change_request', 'normal', 24, 72)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_mgmt, 'change_request', 'low', 24, 72)
    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
END $$;

-- ---------------------------------------------------------------------------
-- Seed email templates
-- ---------------------------------------------------------------------------
INSERT INTO ticket_email_templates (template_name, subject, html_body) VALUES
(
    'ticket_created',
    '[{{ticket_ref}}] Your support request has been received — {{title}}',
    '<p>Dear {{customer_name}},</p>
<p>We have received your support request and assigned it reference number <strong>{{ticket_ref}}</strong>.</p>
<p><strong>Subject:</strong> {{title}}<br>
<strong>Priority:</strong> {{priority}}<br>
<strong>Assigned team:</strong> {{to_dept}}</p>
<p>We will contact you as soon as possible.</p>
<p>Thank you,<br>Support Team</p>'
),
(
    'ticket_resolved',
    '[{{ticket_ref}}] Your support request has been resolved — {{title}}',
    '<p>Dear {{customer_name}},</p>
<p>Your support request <strong>{{ticket_ref}}</strong> has been resolved.</p>
<p><strong>Resolution:</strong><br>{{resolution_note}}</p>
<p>If you have any further questions, please don''t hesitate to contact us.</p>
<p>Thank you,<br>Support Team</p>'
),
(
    'ticket_escalated',
    '[{{ticket_ref}}] Ticket escalated — {{title}}',
    '<p>Hello,</p>
<p>Ticket <strong>{{ticket_ref}}</strong> — <em>{{title}}</em> — has been escalated to your team.</p>
<p><strong>Escalation reason:</strong> {{escalation_reason}}<br>
<strong>Priority:</strong> {{priority}}<br>
<strong>Current status:</strong> {{status}}</p>
<p>Please review and take action.</p>
<p>Thank you,<br>Support Team</p>'
),
(
    'ticket_assigned',
    '[{{ticket_ref}}] You have been assigned a ticket — {{title}}',
    '<p>Hello {{assigned_to}},</p>
<p>Ticket <strong>{{ticket_ref}}</strong> has been assigned to you.</p>
<p><strong>Subject:</strong> {{title}}<br>
<strong>Priority:</strong> {{priority}}<br>
<strong>Type:</strong> {{ticket_type}}</p>
<p>Please review and take action at your earliest convenience.</p>
<p>Thank you,<br>Support Team</p>'
),
(
    'ticket_pending_approval',
    '[{{ticket_ref}}] Approval required — {{title}}',
    '<p>Hello,</p>
<p>Ticket <strong>{{ticket_ref}}</strong> requires your approval before work can proceed.</p>
<p><strong>Subject:</strong> {{title}}<br>
<strong>Requested by:</strong> {{opened_by}}<br>
<strong>Priority:</strong> {{priority}}</p>
<p>Please log in to review and approve or reject this request.</p>
<p>Thank you,<br>Support Team</p>'
),
(
    'ticket_sla_breach',
    '[{{ticket_ref}}] SLA BREACH — {{title}}',
    '<p><strong>⚠️ SLA Breach Alert</strong></p>
<p>Ticket <strong>{{ticket_ref}}</strong> has breached its SLA.</p>
<p><strong>Subject:</strong> {{title}}<br>
<strong>Breached SLA:</strong> {{breach_type}}<br>
<strong>Priority:</strong> {{priority}}<br>
<strong>Assigned to:</strong> {{assigned_to}}</p>
<p>Immediate action is required.</p>
<p>Support Team</p>'
)
ON CONFLICT (template_name) DO NOTHING;
