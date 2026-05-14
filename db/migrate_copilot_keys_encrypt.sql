-- Migration: Encrypt Copilot LLM API keys at rest
-- =====================================================================
-- After this migration the openai_api_key and anthropic_api_key columns
-- in copilot_config are treated as opaque blobs: the application layer
-- writes "fernet:<ciphertext>" strings and decrypts them at runtime.
--
-- Existing plaintext values are handled gracefully:
--   * api/copilot.py _decrypt_llm_key() passes through any value that
--     does NOT start with "fernet:" unchanged (backward-compatible read).
--   * On the next PUT /api/copilot/config the values will be re-written
--     as Fernet ciphertext automatically.
--
-- No DDL change required — the column type remains TEXT.
-- This file is a marker migration only; run migrate_copilot_keys.py to
-- actively re-encrypt any existing plaintext rows in a live database.
-- =====================================================================

-- Verify the table exists (no-op if already present).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                 WHERE table_name = 'copilot_config') THEN
    RAISE NOTICE 'copilot_config table does not exist — skipping.';
  ELSE
    RAISE NOTICE 'copilot_config key encryption migration marker applied.';
  END IF;
END;
$$;
