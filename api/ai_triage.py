"""AI Incident Triage evaluation helpers."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from psycopg2.extras import RealDictCursor

from cache import _get_client as _redis_client
from copilot_context import build_infra_context
from copilot_llm import ask_llm
from db_pool import get_connection

logger = logging.getLogger("copilot.ai_triage")

_SEVERITY_ORDER = {
    "info": 0,
    "warning": 1,
    "high": 2,
    "critical": 3,
}


def _severity_meets_threshold(severity: str, minimum: str) -> bool:
    sev = _SEVERITY_ORDER.get((severity or "info").lower(), 0)
    minv = _SEVERITY_ORDER.get((minimum or "critical").lower(), _SEVERITY_ORDER["critical"])
    return sev >= minv


def _load_triage_runtime_config() -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "backend": os.getenv("COPILOT_BACKEND", "builtin"),
        "ollama_url": os.getenv("COPILOT_OLLAMA_URL", "http://localhost:11434"),
        "ollama_model": os.getenv("COPILOT_OLLAMA_MODEL", "llama3"),
        "openai_api_key": os.getenv("COPILOT_OPENAI_API_KEY", ""),
        "openai_model": os.getenv("COPILOT_OPENAI_MODEL", "gpt-4o-mini"),
        "anthropic_api_key": os.getenv("COPILOT_ANTHROPIC_API_KEY", ""),
        "anthropic_model": os.getenv("COPILOT_ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        "redact_sensitive": os.getenv("COPILOT_REDACT_SENSITIVE", "true").lower() in ("true", "1", "yes"),
        "ai_triage_enabled": False,
        "ai_triage_min_severity": "critical",
        "ai_triage_max_per_hour": 10,
        "ai_triage_notify_email": False,
    }

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'copilot_config'
                    """
                )
                cols = {r["column_name"] for r in cur.fetchall()}
                if not cols:
                    return cfg

                wanted = [
                    "backend",
                    "ollama_url",
                    "ollama_model",
                    "openai_api_key",
                    "openai_model",
                    "anthropic_api_key",
                    "anthropic_model",
                    "redact_sensitive",
                    "ai_triage_enabled",
                    "ai_triage_min_severity",
                    "ai_triage_max_per_hour",
                    "ai_triage_notify_email",
                ]
                select_cols = [c for c in wanted if c in cols]
                cur.execute(f"SELECT {', '.join(select_cols)} FROM copilot_config WHERE id = 1")
                row = cur.fetchone() or {}
                for key in select_cols:
                    if row.get(key) is not None:
                        cfg[key] = row.get(key)
    except Exception:
        logger.debug("ai_triage: could not read copilot_config, using defaults", exc_info=True)

    return cfg


def _extract_json_object(text: str) -> Optional[dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None

    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _normalize_brief(raw_answer: str) -> tuple[str, str, str, Optional[str]]:
    obj = _extract_json_object(raw_answer)
    if not obj:
        analysis = (raw_answer or "AI triage generated a non-structured response.").strip()
        if not analysis:
            analysis = "AI triage did not return analysis text."
        return analysis[:3000], "Review the related event and execute the appropriate runbook.", "medium", None

    analysis = str(obj.get("analysis") or "").strip()
    recommendation = str(obj.get("recommendation") or "").strip()
    risk_level = str(obj.get("risk_level") or "medium").strip().lower()
    runbook_name = obj.get("runbook_name")

    if not analysis:
        analysis = (raw_answer or "AI triage response parsed without analysis.").strip()[:3000]
    if not recommendation:
        recommendation = "Review the event details and execute the recommended runbook if impact is confirmed."
    if risk_level not in ("low", "medium", "high", "critical"):
        risk_level = "medium"

    if runbook_name is not None:
        runbook_name = str(runbook_name).strip() or None

    return analysis[:3000], recommendation[:3000], risk_level, runbook_name


def _publish_incident_brief(payload: dict[str, Any]) -> None:
    try:
        rc = _redis_client()
        if rc is None:
            return
        rc.publish("pf9:incident_briefs", json.dumps(payload))
    except Exception:
        logger.debug("ai_triage: failed to publish incident brief", exc_info=True)


def _notify_via_email_if_enabled(cfg: dict[str, Any], payload: dict[str, Any]) -> None:
    if not bool(cfg.get("ai_triage_notify_email")):
        return

    recipients_raw = os.getenv("PF9_AI_TRIAGE_NOTIFY_EMAILS", "").strip()
    if not recipients_raw:
        logger.info("ai_triage: email notification enabled but PF9_AI_TRIAGE_NOTIFY_EMAILS is empty")
        return

    recipients = [x.strip() for x in recipients_raw.split(",") if x.strip()]
    if not recipients:
        return

    subject = f"[AI Triage] {payload.get('risk_level', 'medium').upper()} - {payload.get('event_type', 'event')}"
    html = (
        f"<h3>AI Incident Brief</h3>"
        f"<p><b>Event:</b> {payload.get('event_type')}</p>"
        f"<p><b>Project:</b> {payload.get('project_name') or payload.get('project_id') or '-'} </p>"
        f"<p><b>Entity:</b> {payload.get('entity_name') or '-'} </p>"
        f"<p><b>Risk:</b> {payload.get('risk_level')}</p>"
        f"<p><b>Analysis:</b> {payload.get('analysis')}</p>"
        f"<p><b>Recommendation:</b> {payload.get('recommendation')}</p>"
    )

    try:
        from smtp_helper import send_email

        send_email(recipients, subject, html)
    except Exception:
        logger.debug("ai_triage: failed to send email notification", exc_info=True)


def evaluate_ai_triage(
    event_id: int,
    event_type: str,
    severity: str,
    entity_name: Optional[str],
    project_id: Optional[str],
    project_name: Optional[str],
    metadata: Optional[dict[str, Any]],
) -> Optional[int]:
    """Generate and persist an AI incident brief for high-severity events."""
    cfg = _load_triage_runtime_config()

    if not bool(cfg.get("ai_triage_enabled", False)):
        return None

    min_sev = str(cfg.get("ai_triage_min_severity") or "critical").lower()
    if not _severity_meets_threshold(severity, min_sev):
        return None

    backend = str(cfg.get("backend") or "builtin").lower()
    if backend == "builtin":
        return None

    if backend == "openai" and not str(cfg.get("openai_api_key") or "").strip():
        return None
    if backend == "anthropic" and not str(cfg.get("anthropic_api_key") or "").strip():
        return None

    max_per_hour = int(cfg.get("ai_triage_max_per_hour") or 10)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM incident_briefs
                WHERE generated_at > NOW() - interval '1 hour'
                """
            )
            if int(cur.fetchone()[0]) >= max_per_hour:
                return None

    redact = bool(cfg.get("redact_sensitive", True)) and backend in ("openai", "anthropic")
    context = build_infra_context(redact=redact)

    prompt = (
        "Generate a concise incident triage brief in strict JSON. "
        "Return only one JSON object with keys: analysis, recommendation, risk_level, runbook_name. "
        "risk_level must be one of: low, medium, high, critical. "
        "If no runbook suggestion is clear, set runbook_name to null.\n\n"
        f"Event ID: {event_id}\n"
        f"Event Type: {event_type}\n"
        f"Severity: {severity}\n"
        f"Project ID: {project_id or ''}\n"
        f"Project Name: {project_name or ''}\n"
        f"Entity Name: {entity_name or ''}\n"
        f"Metadata JSON: {json.dumps(metadata or {}, default=str)}"
    )

    answer, backend_used, _tokens, _external = ask_llm(
        backend=backend,
        question=prompt,
        context=context,
        system_prompt="You are an SRE incident triage assistant. Be concise, concrete, and action-oriented.",
        ollama_url=str(cfg.get("ollama_url") or "http://localhost:11434"),
        ollama_model=str(cfg.get("ollama_model") or "llama3"),
        openai_api_key=str(cfg.get("openai_api_key") or ""),
        openai_model=str(cfg.get("openai_model") or "gpt-4o-mini"),
        anthropic_api_key=str(cfg.get("anthropic_api_key") or ""),
        anthropic_model=str(cfg.get("anthropic_model") or "claude-sonnet-4-20250514"),
    )

    if not answer:
        return None

    analysis, recommendation, risk_level, runbook_name = _normalize_brief(answer)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO incident_briefs
                    (event_id, event_type, entity_name, project_id, project_name,
                     analysis, recommendation, risk_level, runbook_name)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, generated_at
                """,
                (
                    event_id,
                    event_type,
                    entity_name,
                    project_id,
                    project_name,
                    analysis,
                    recommendation,
                    risk_level,
                    runbook_name,
                ),
            )
            row = dict(cur.fetchone())
            conn.commit()

    payload = {
        "id": int(row["id"]),
        "event_id": int(event_id),
        "event_type": event_type,
        "severity": severity,
        "risk_level": risk_level,
        "project_id": project_id,
        "project_name": project_name,
        "entity_name": entity_name,
        "analysis": analysis,
        "recommendation": recommendation,
        "runbook_name": runbook_name,
        "generated_at": row["generated_at"].isoformat() if row.get("generated_at") else None,
        "backend_used": backend_used,
    }

    _publish_incident_brief(payload)
    _notify_via_email_if_enabled(cfg, payload)
    return int(row["id"])
