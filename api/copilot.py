"""
copilot.py — FastAPI router for Ops Copilot.

Endpoints:
  POST /api/copilot/ask              — ask a question (dispatches to intent/LLM)
  GET  /api/copilot/suggestions      — quick-start suggestion chips
  GET  /api/copilot/history          — conversation history for current user
  GET  /api/copilot/config           — read copilot configuration (admin)
  PUT  /api/copilot/config           — update copilot configuration (admin)
  POST /api/copilot/test-connection  — test LLM backend connectivity (admin)
  POST /api/copilot/feedback         — submit feedback on an answer
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from db_pool import get_connection
from copilot_intents import match_intent, get_suggestion_chips, _extract_scope
from copilot_context import build_infra_context
from copilot_llm import ask_llm, test_ollama, test_openai, test_anthropic

logger = logging.getLogger("copilot")

router = APIRouter(prefix="/api/copilot", tags=["copilot"])

# ---------------------------------------------------------------------------
# Environment defaults (overridden by DB copilot_config at runtime)
# ---------------------------------------------------------------------------

DEFAULT_BACKEND = os.getenv("COPILOT_BACKEND", "builtin")
DEFAULT_OLLAMA_URL = os.getenv("COPILOT_OLLAMA_URL", "http://localhost:11434")
DEFAULT_OLLAMA_MODEL = os.getenv("COPILOT_OLLAMA_MODEL", "llama3")
DEFAULT_OPENAI_KEY = os.getenv("COPILOT_OPENAI_API_KEY", "")
DEFAULT_OPENAI_MODEL = os.getenv("COPILOT_OPENAI_MODEL", "gpt-4o-mini")
DEFAULT_ANTHROPIC_KEY = os.getenv("COPILOT_ANTHROPIC_API_KEY", "")
DEFAULT_ANTHROPIC_MODEL = os.getenv("COPILOT_ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
DEFAULT_REDACT = os.getenv("COPILOT_REDACT_SENSITIVE", "true").lower() in ("true", "1", "yes")
DEFAULT_SYSTEM_PROMPT = os.getenv(
    "COPILOT_SYSTEM_PROMPT",
    "You are Ops Copilot, an AI assistant for Platform9 infrastructure management. "
    "Answer concisely using the provided infrastructure context. If you are unsure, say so.",
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)


class AskResponse(BaseModel):
    answer: str
    intent: str | None = None
    backend_used: str = "builtin"
    confidence: float | None = None
    tokens_used: int | None = None
    data_sent_external: bool = False
    history_id: int | None = None


class FeedbackRequest(BaseModel):
    history_id: int
    helpful: bool
    comment: str | None = None


class ConfigUpdate(BaseModel):
    backend: str | None = None
    ollama_url: str | None = None
    ollama_model: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str | None = None
    redact_sensitive: bool | None = None
    system_prompt: str | None = None


class TestConnectionRequest(BaseModel):
    backend: str                  # ollama | openai | anthropic
    url: str | None = None        # for ollama
    api_key: str | None = None    # for openai / anthropic
    model: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_config() -> dict:
    """Load the singleton copilot_config row, falling back to env defaults."""
    try:
        with get_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM copilot_config WHERE id = 1")
            row = cur.fetchone()
            if row:
                return dict(row)
    except Exception:
        logger.debug("copilot_config table not available yet, using env defaults")

    return {
        "backend": DEFAULT_BACKEND,
        "ollama_url": DEFAULT_OLLAMA_URL,
        "ollama_model": DEFAULT_OLLAMA_MODEL,
        "openai_api_key": DEFAULT_OPENAI_KEY,
        "openai_model": DEFAULT_OPENAI_MODEL,
        "anthropic_api_key": DEFAULT_ANTHROPIC_KEY,
        "anthropic_model": DEFAULT_ANTHROPIC_MODEL,
        "redact_sensitive": DEFAULT_REDACT,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "max_history_per_user": 200,
    }


def _extract_username(request: Request) -> str:
    """
    Pull username from the token payload stashed by the auth middleware.
    Falls back to 'anonymous' when auth is disabled.
    """
    token_data = getattr(request.state, "token_data", None)
    if token_data and hasattr(token_data, "username"):
        return token_data.username
    # Fallback: try the Authorization header directly
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            from auth import verify_token
            td = verify_token(auth[7:])
            if td:
                return td.username
        except Exception:
            pass
    return "anonymous"


def _save_history(username, question, answer, intent, backend, confidence, tokens, ext):
    """Insert into copilot_history and return the new row id."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO copilot_history
                    (username, question, answer, intent, backend_used,
                     confidence, tokens_used, data_sent_external)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (username, question, answer, intent, backend,
                  confidence, tokens, ext))
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as exc:
        logger.warning("Failed to save copilot history: %s", exc)
        return None


def _trim_history(username: str, max_rows: int):
    """Keep only the latest `max_rows` entries per user."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                DELETE FROM copilot_history
                WHERE id IN (
                    SELECT id FROM copilot_history
                    WHERE username = %s
                    ORDER BY created_at DESC
                    OFFSET %s
                )
            """, (username, max_rows))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest, request: Request):
    """
    Main entry point — answer a user's natural-language question.

    Flow:
      1. If backend is 'builtin', try the intent engine first.
      2. If backend is 'ollama'/'openai'/'anthropic', call the LLM
         with infrastructure context.  If LLM fails, fall back to
         the intent engine.
      3. If nothing matches, return a friendly "I don't know" message.
    """
    username = _extract_username(request)
    cfg = _get_config()
    backend = cfg["backend"]
    question = body.question.strip()

    answer = ""
    intent_key = None
    confidence = None
    tokens = None
    data_sent = False
    backend_used = backend

    # ── Tier 1: Built-in intent engine ─────────────────────────────────
    intent_match = match_intent(question)

    if backend == "builtin":
        # Pure intent engine mode
        if intent_match:
            try:
                if intent_match.api_handler:
                    # Live API call intent — handler returns the answer directly
                    answer = intent_match.api_handler(question)
                else:
                    # SQL-based intent
                    with get_connection() as conn:
                        cur = conn.cursor(cursor_factory=RealDictCursor)
                        cur.execute(intent_match.sql, intent_match.params)
                        rows = cur.fetchall()
                    answer = intent_match.formatter(rows) if intent_match.formatter else str(rows)
                intent_key = intent_match.intent_key
                confidence = intent_match.confidence
                backend_used = "builtin"
            except Exception as exc:
                logger.error("Intent query failed (%s): %s", intent_match.intent_key, exc)
                answer = f"I matched intent **{intent_match.display_name}** but the query failed. Please try again."
        else:
            scope_hint = _extract_scope(question)
            answer = (
                "I couldn't match that to a built-in query. Here are some tips:\n\n"
                "**Try phrasing like:**\n"
                "- \"How many VMs?\" / \"How many powered on VMs?\"\n"
                "- \"Show VMs on tenant <your-tenant>\" / \"List powered off VMs\"\n"
                "- \"CPU capacity\" / \"Memory usage\" / \"Storage capacity\"\n"
                "- \"VMs in error\" / \"Down hosts\" / \"Drift summary\"\n"
                "- \"Infrastructure overview\" / \"Snapshot summary\"\n\n"
                "**Scope by tenant:** add *on tenant <name>* or *for project <name>*\n\n"
                "Or click a suggestion chip below for instant answers.\n\n"
                "💡 For free-form questions, switch to an LLM backend (Ollama / OpenAI / Anthropic) in ⚙️ Settings."
            )
            backend_used = "builtin"

    else:
        # ── Tier 2 / 3: LLM backends ──────────────────────────────────
        redact = cfg.get("redact_sensitive", True) and backend in ("openai", "anthropic")
        context = build_infra_context(redact=redact)
        system_prompt = cfg.get("system_prompt", DEFAULT_SYSTEM_PROMPT)

        # If we have a high-confidence intent, prepend its data for the LLM
        if intent_match and intent_match.confidence >= 0.7:
            try:
                if intent_match.api_handler:
                    intent_data = intent_match.api_handler(question)
                else:
                    with get_connection() as conn:
                        cur = conn.cursor(cursor_factory=RealDictCursor)
                        cur.execute(intent_match.sql, intent_match.params)
                        rows = cur.fetchall()
                        intent_data = intent_match.formatter(rows) if intent_match.formatter else str(rows)
                context += f"\n\nRELEVANT QUERY RESULT ({intent_match.display_name}):\n{intent_data}"
                intent_key = intent_match.intent_key
                confidence = intent_match.confidence
            except Exception:
                pass

        answer, backend_used, tokens, data_sent = ask_llm(
            backend=backend,
            question=question,
            context=context,
            system_prompt=system_prompt,
            ollama_url=cfg.get("ollama_url", DEFAULT_OLLAMA_URL),
            ollama_model=cfg.get("ollama_model", DEFAULT_OLLAMA_MODEL),
            openai_api_key=cfg.get("openai_api_key", DEFAULT_OPENAI_KEY),
            openai_model=cfg.get("openai_model", DEFAULT_OPENAI_MODEL),
            anthropic_api_key=cfg.get("anthropic_api_key", DEFAULT_ANTHROPIC_KEY),
            anthropic_model=cfg.get("anthropic_model", DEFAULT_ANTHROPIC_MODEL),
        )

        # Fallback: if LLM returned empty, try intent engine
        if not answer and intent_match:
            try:
                if intent_match.api_handler:
                    answer = intent_match.api_handler(question)
                else:
                    with get_connection() as conn:
                        cur = conn.cursor(cursor_factory=RealDictCursor)
                        cur.execute(intent_match.sql, intent_match.params)
                        rows = cur.fetchall()
                    answer = intent_match.formatter(rows) if intent_match.formatter else str(rows)
                intent_key = intent_match.intent_key
                confidence = intent_match.confidence
                backend_used = "builtin"
                data_sent = False
            except Exception:
                pass

        if not answer:
            answer = (
                "I couldn't get an answer from the LLM backend and no built-in intent matched. "
                "Please try rephrasing or check the LLM connection in Settings."
            )
            backend_used = "builtin"

    # ── Save to history ────────────────────────────────────────────────
    history_id = _save_history(
        username, question, answer, intent_key, backend_used,
        confidence, tokens, data_sent,
    )
    _trim_history(username, cfg.get("max_history_per_user", 200))

    return AskResponse(
        answer=answer,
        intent=intent_key,
        backend_used=backend_used,
        confidence=confidence,
        tokens_used=tokens,
        data_sent_external=data_sent,
        history_id=history_id,
    )


@router.get("/suggestions")
async def suggestions():
    """Return quick-start suggestion chips for the UI."""
    return {"suggestions": get_suggestion_chips()}


@router.get("/history")
async def history(request: Request, limit: int = 50):
    """Return conversation history for the current user."""
    username = _extract_username(request)
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, question, answer, intent, backend_used,
                   confidence, tokens_used, data_sent_external, created_at
            FROM copilot_history
            WHERE username = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (username, limit))
        rows = cur.fetchall()
    # Convert datetimes to ISO strings
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
    return {"history": rows}


@router.get("/config")
async def get_config(request: Request):
    """Return current copilot configuration (admin-only, keys masked)."""
    cfg = _get_config()
    # Mask API keys for display
    safe = dict(cfg)
    for k in ("openai_api_key", "anthropic_api_key"):
        v = safe.get(k, "")
        if v and len(v) > 8:
            safe[k] = v[:4] + "…" + v[-4:]
        elif v:
            safe[k] = "****"
    # Remove internal fields
    safe.pop("id", None)
    if safe.get("updated_at"):
        safe["updated_at"] = safe["updated_at"].isoformat() if hasattr(safe["updated_at"], "isoformat") else str(safe["updated_at"])
    return safe


@router.put("/config")
async def update_config(body: ConfigUpdate, request: Request):
    """Update copilot configuration (admin-only)."""
    username = _extract_username(request)
    cfg = _get_config()

    updates = {}
    if body.backend is not None:
        if body.backend not in ("builtin", "ollama", "openai", "anthropic"):
            raise HTTPException(400, "Invalid backend. Choose: builtin, ollama, openai, anthropic")
        updates["backend"] = body.backend
    if body.ollama_url is not None:
        updates["ollama_url"] = body.ollama_url
    if body.ollama_model is not None:
        updates["ollama_model"] = body.ollama_model
    if body.openai_api_key is not None:
        updates["openai_api_key"] = body.openai_api_key
    if body.openai_model is not None:
        updates["openai_model"] = body.openai_model
    if body.anthropic_api_key is not None:
        updates["anthropic_api_key"] = body.anthropic_api_key
    if body.anthropic_model is not None:
        updates["anthropic_model"] = body.anthropic_model
    if body.redact_sensitive is not None:
        updates["redact_sensitive"] = body.redact_sensitive
    if body.system_prompt is not None:
        updates["system_prompt"] = body.system_prompt

    if not updates:
        raise HTTPException(400, "No fields to update")

    set_clauses = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [username]

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE copilot_config SET {set_clauses}, updated_at = now(), updated_by = %s WHERE id = 1",
            values,
        )

    return {"ok": True, "updated": list(updates.keys())}


@router.post("/test-connection")
async def test_connection(body: TestConnectionRequest):
    """Test connectivity to an LLM backend."""
    if body.backend == "ollama":
        result = test_ollama(url=body.url or DEFAULT_OLLAMA_URL)
    elif body.backend == "openai":
        if not body.api_key:
            raise HTTPException(400, "api_key is required for OpenAI")
        result = test_openai(api_key=body.api_key, model=body.model or "gpt-4o-mini")
    elif body.backend == "anthropic":
        if not body.api_key:
            raise HTTPException(400, "api_key is required for Anthropic")
        result = test_anthropic(api_key=body.api_key, model=body.model or "claude-sonnet-4-20250514")
    else:
        raise HTTPException(400, "Unknown backend")
    return result


@router.post("/feedback")
async def feedback(body: FeedbackRequest, request: Request):
    """Submit feedback (thumbs up/down) on a copilot answer."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO copilot_feedback (history_id, helpful, comment)
            VALUES (%s, %s, %s)
        """, (body.history_id, body.helpful, body.comment))
    return {"ok": True}
