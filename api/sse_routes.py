"""
SSE — Server-Sent Events live event stream  (v2.12.0)

GET /api/events/stream
-----------------------
Streams real-time operational events to authenticated browser clients using
the W3C Server-Sent Events protocol (``text/event-stream``).

Events are published to Redis channel ``pf9:live_events`` by
``event_bus._write_event()`` immediately after each operational event is
committed to the database.

Event payload  (JSON):
  { "id": <int>, "type": <str>, "title": <str>, "severity": <str>,
    "category": <str>, "entity_type": <str>, "entity_id": <str>,
    "occurred_at": <iso8601> }

Keepalive: an SSE comment ``: keepalive`` is emitted every 25 s so the
browser ``EventSource`` does not time out the connection.

Auth: requires a valid JWT (``access_token`` cookie or
``Authorization: Bearer`` header).

Reconnect: browsers auto-reconnect on disconnect.  The ``id`` field in each
event allows clients to implement resume-from-last-seen in future.

nginx / proxy: ``X-Accel-Buffering: no`` disables nginx proxy buffering so
events are not held in the proxy buffer before reaching the browser.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from auth import require_authentication

logger = logging.getLogger("pf9.sse")

router = APIRouter(prefix="/api", tags=["events"])

_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
_CHANNELS = ("pf9:live_events", "pf9:incident_briefs")
_HEARTBEAT_S = 25  # seconds between keepalive comments


# ---------------------------------------------------------------------------
# SSE generator
# ---------------------------------------------------------------------------

async def _sse_generator(request: Request) -> AsyncGenerator[str, None]:
    """
    Async generator that:
    1. Opens a Redis pub/sub subscription on live-events + incident-brief channels.
      2. Yields SSE ``data:`` lines for every message received.
      3. Yields ``: keepalive`` comments every 25 s to prevent proxy timeouts.
      4. Exits cleanly when the client disconnects or an error occurs.
    """
    try:
        # redis >= 4.2 ships redis.asyncio; redis >= 5.0 (our requirement) is fine
        from redis.asyncio import from_url as _aio_redis  # type: ignore[import]
    except ImportError:
        logger.warning("sse: redis.asyncio unavailable — cannot serve SSE stream")
        yield 'data: {"type":"system","title":"SSE requires redis>=4.2"}\n\n'
        return

    client = _aio_redis(
        _REDIS_URL,
        socket_connect_timeout=3,
        socket_timeout=60,
        decode_responses=True,
    )
    pubsub = client.pubsub()

    try:
        await pubsub.subscribe(*_CHANNELS)
        logger.debug("sse: client connected, subscribed to %s", ", ".join(_CHANNELS))

        while True:
            # Check for client disconnect on each iteration
            if await request.is_disconnected():
                logger.debug("sse: client disconnected cleanly")
                break

            # get_message with timeout=_HEARTBEAT_S blocks until a message
            # arrives or the timeout elapses (returns None on timeout).
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=float(_HEARTBEAT_S),
            )

            if msg and msg.get("type") == "message":
                channel = msg.get("channel")
                if channel == "pf9:incident_briefs":
                    yield f"event: incident_brief\ndata: {msg['data']}\n\n"
                else:
                    yield f"data: {msg['data']}\n\n"
            else:
                # No message in HEARTBEAT_S seconds — send keepalive comment
                yield ": keepalive\n\n"

    except asyncio.CancelledError:
        logger.debug("sse: generator cancelled")
    except Exception as exc:
        logger.warning("sse: unexpected stream error: %s", exc)
    finally:
        try:
            await pubsub.unsubscribe(*_CHANNELS)
            await client.aclose()
        except Exception:
            pass
        logger.debug("sse: generator exited, pubsub closed")


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/events/stream")
async def event_stream(
    request: Request,
    _user=Depends(require_authentication),
):
    """
    SSE stream of real-time platform events.

    Connect using ``EventSource('/api/events/stream', {withCredentials: true})``.
    Each event is a JSON payload; keepalive comments arrive every 25 s.

    Requires authentication (JWT cookie or Authorization header).
    """
    return StreamingResponse(
        _sse_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",    # disable nginx proxy buffering
            "Connection": "keep-alive",
        },
    )
