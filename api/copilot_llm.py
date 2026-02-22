"""
copilot_llm.py — LLM abstraction layer for Ops Copilot (Tiers 2 & 3).

Provides a unified ``ask_llm()`` interface that dispatches to:
  • Ollama   (local, self-hosted)
  • OpenAI   (external)
  • Anthropic (external)

Each backend uses HTTP / SDK calls and returns a plain-text answer.
Connection testing is also exposed for the Settings UI.

Dependencies (optional — only needed if you use the respective backend):
  • ``requests`` (already in requirements.txt — used for Ollama)
  • ``openai``   (add to requirements.txt if using OpenAI)
  • ``anthropic`` (add to requirements.txt if using Anthropic)
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import requests

logger = logging.getLogger("copilot.llm")


# ---------------------------------------------------------------------------
# Ollama (Tier 2 — local LLM)
# ---------------------------------------------------------------------------

def ask_ollama(
    question: str,
    context: str,
    system_prompt: str,
    url: str = "http://localhost:11434",
    model: str = "llama3",
    timeout: int = 120,
) -> Tuple[str, Optional[int]]:
    """
    Send a chat completion request to a local Ollama instance.
    Returns (answer_text, tokens_used_or_None).
    Raises on network / timeout errors.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Infrastructure context:\n{context}\n\nUser question: {question}"},
    ]
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    resp = requests.post(f"{url.rstrip('/')}/api/chat", json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    answer = data.get("message", {}).get("content", "").strip()
    tokens = data.get("eval_count")
    return answer, tokens


def test_ollama(url: str = "http://localhost:11434", timeout: int = 5) -> dict:
    """Ping Ollama and return status + available models."""
    try:
        resp = requests.get(f"{url.rstrip('/')}/api/tags", timeout=timeout)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        return {"ok": True, "models": models}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# OpenAI (Tier 3 — external LLM)
# ---------------------------------------------------------------------------

def ask_openai(
    question: str,
    context: str,
    system_prompt: str,
    api_key: str,
    model: str = "gpt-4o-mini",
    timeout: int = 60,
) -> Tuple[str, Optional[int]]:
    """
    Call the OpenAI Chat Completions API.
    Returns (answer_text, tokens_used).
    """
    try:
        from openai import OpenAI  # lazy import — package may not be installed
    except ImportError:
        raise RuntimeError(
            "The 'openai' Python package is not installed. "
            "Run: pip install openai"
        )

    client = OpenAI(api_key=api_key, timeout=timeout)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Infrastructure context:\n{context}\n\nUser question: {question}"},
        ],
        max_tokens=1024,
        temperature=0.3,
    )
    answer = resp.choices[0].message.content.strip()
    tokens = resp.usage.total_tokens if resp.usage else None
    return answer, tokens


def test_openai(api_key: str, model: str = "gpt-4o-mini") -> dict:
    """Verify the API key by listing models."""
    try:
        from openai import OpenAI
    except ImportError:
        return {"ok": False, "error": "openai package not installed"}
    try:
        client = OpenAI(api_key=api_key, timeout=10)
        # A lightweight call to verify key validity
        client.models.retrieve(model)
        return {"ok": True, "model": model}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Anthropic (Tier 3 — external LLM)
# ---------------------------------------------------------------------------

def ask_anthropic(
    question: str,
    context: str,
    system_prompt: str,
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
    timeout: int = 60,
) -> Tuple[str, Optional[int]]:
    """
    Call the Anthropic Messages API.
    Returns (answer_text, tokens_used).
    """
    try:
        import anthropic  # lazy import
    except ImportError:
        raise RuntimeError(
            "The 'anthropic' Python package is not installed. "
            "Run: pip install anthropic"
        )

    client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=system_prompt,
        messages=[
            {"role": "user", "content": f"Infrastructure context:\n{context}\n\nUser question: {question}"},
        ],
    )
    answer = resp.content[0].text.strip()
    tokens = (resp.usage.input_tokens or 0) + (resp.usage.output_tokens or 0)
    return answer, tokens


def test_anthropic(api_key: str, model: str = "claude-sonnet-4-20250514") -> dict:
    """Verify the API key with a tiny request."""
    try:
        import anthropic
    except ImportError:
        return {"ok": False, "error": "anthropic package not installed"}
    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=10)
        client.messages.create(
            model=model,
            max_tokens=5,
            messages=[{"role": "user", "content": "Hi"}],
        )
        return {"ok": True, "model": model}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Unified dispatcher
# ---------------------------------------------------------------------------

def ask_llm(
    backend: str,
    question: str,
    context: str,
    system_prompt: str,
    *,
    ollama_url: str = "http://localhost:11434",
    ollama_model: str = "llama3",
    openai_api_key: str = "",
    openai_model: str = "gpt-4o-mini",
    anthropic_api_key: str = "",
    anthropic_model: str = "claude-sonnet-4-20250514",
) -> Tuple[str, str, Optional[int], bool]:
    """
    Dispatch to the requested backend.

    Returns:
        (answer, backend_used, tokens, data_sent_external)

    If the requested backend fails, falls back to built-in (returns empty answer
    so the router can run the intent engine instead).
    """
    data_sent = False

    try:
        if backend == "ollama":
            answer, tokens = ask_ollama(question, context, system_prompt,
                                        url=ollama_url, model=ollama_model)
            return answer, "ollama", tokens, False

        elif backend == "openai":
            if not openai_api_key:
                raise ValueError("OpenAI API key not configured")
            answer, tokens = ask_openai(question, context, system_prompt,
                                        api_key=openai_api_key, model=openai_model)
            return answer, "openai", tokens, True

        elif backend == "anthropic":
            if not anthropic_api_key:
                raise ValueError("Anthropic API key not configured")
            answer, tokens = ask_anthropic(question, context, system_prompt,
                                           api_key=anthropic_api_key, model=anthropic_model)
            return answer, "anthropic", tokens, True

        else:
            # Unknown backend → treat as builtin (no LLM call)
            return "", "builtin", None, False

    except Exception as exc:
        logger.warning("LLM backend '%s' failed, falling back to built-in: %s", backend, exc)
        return "", "builtin", None, data_sent
