-- =====================================================================
-- Migration v2.4.0: Notification Dead-Letter Queue
--
-- Adds a retry queue for failed notification sends.
-- Failed emails are retried up to DLQ_MAX_ATTEMPTS (default 3) times
-- with exponential back-off (5 min → 15 min → 60 min) before being
-- moved to 'dead_lettered' status in notification_log.
-- =====================================================================

CREATE TABLE IF NOT EXISTS notification_retry_queue (
    id              BIGSERIAL   PRIMARY KEY,
    username        TEXT        NOT NULL,
    email           TEXT        NOT NULL,
    event_type      TEXT        NOT NULL,
    event_id        TEXT,
    dedup_key       TEXT        NOT NULL,
    subject         TEXT        NOT NULL,
    template_name   TEXT        NOT NULL,
    event_json      JSONB       NOT NULL,
    attempt_count   INT         NOT NULL DEFAULT 0,
    max_attempts    INT         NOT NULL DEFAULT 3,
    next_retry_at   TIMESTAMPTZ NOT NULL DEFAULT now() + INTERVAL '5 minutes',
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dedup_key, username)
);

-- Efficient polling index: only rows that are due and have attempts remaining
CREATE INDEX IF NOT EXISTS idx_notification_retry_due
    ON notification_retry_queue (next_retry_at)
    WHERE attempt_count < max_attempts;

CREATE INDEX IF NOT EXISTS idx_notification_retry_username
    ON notification_retry_queue (username);

-- Grant the notification worker service role access to the new table.
-- pf9_notification_svc (created in migrate_v2_3_0_db_roles.sql) needs
-- full DML access to enqueue retries and process them.
GRANT SELECT, INSERT, UPDATE, DELETE
    ON notification_retry_queue
    TO pf9_notification_svc;

GRANT USAGE, SELECT
    ON SEQUENCE notification_retry_queue_id_seq
    TO pf9_notification_svc;
