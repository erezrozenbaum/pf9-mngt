-- B8.1: Self-service password reset token table
-- Tokens are stored as SHA-256 hashes; 24-hour TTL enforced server-side on use.
-- Existing unused tokens for a user are invalidated when a new request is made.

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id          BIGSERIAL    PRIMARY KEY,
    username    TEXT         NOT NULL,
    token_hash  TEXT         NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ  NOT NULL DEFAULT (now() + INTERVAL '24 hours'),
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prt_username   ON password_reset_tokens(username);
CREATE INDEX IF NOT EXISTS idx_prt_token_hash ON password_reset_tokens(token_hash);
