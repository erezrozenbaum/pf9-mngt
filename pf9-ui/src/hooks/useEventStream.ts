/**
 * useEventStream — SSE real-time event hook  (v2.12.0)
 *
 * Subscribes to GET /api/events/stream and calls `onEvent` for every
 * operational event the server pushes.  Auto-reconnects on disconnect with
 * exponential back-off (1 s → 2 s → 4 s … capped at 30 s).
 *
 * Only active when `enabled` is true (should be tied to `isAuthenticated`).
 */

import { useEffect, useRef, useCallback } from 'react';

export interface LiveEvent {
  id: number;
  type: string;
  title: string;
  severity: 'info' | 'warning' | 'critical';
  category: string;
  entity_type: string;
  entity_id: string;
  occurred_at: string;
}

interface Options {
  /** Invoked for every event received from the stream. */
  onEvent: (event: LiveEvent) => void;
  /** Whether the stream should be open.  Defaults to true. */
  enabled?: boolean;
}

const _API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? '';
const _MAX_BACKOFF_MS = 30_000;

export function useEventStream({ onEvent, enabled = true }: Options): void {
  const esRef = useRef<EventSource | null>(null);
  const backoffRef = useRef(1_000);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Keep a stable ref so the connect callback doesn't need to re-run
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const connect = useCallback(() => {
    if (!enabledRef.current) return;

    // Close any stale connection first
    esRef.current?.close();
    esRef.current = null;

    const url = `${_API_BASE}/api/events/stream`;
    const es = new EventSource(url, { withCredentials: true });
    esRef.current = es;

    es.onmessage = (e: MessageEvent) => {
      try {
        const event: LiveEvent = JSON.parse(e.data as string);
        if (event.type === 'system') return; // internal/diagnostic events
        onEventRef.current(event);
        backoffRef.current = 1_000; // reset back-off on successful message
      } catch {
        // Ignore malformed JSON
      }
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;
      if (!enabledRef.current) return;
      const delay = backoffRef.current;
      backoffRef.current = Math.min(delay * 2, _MAX_BACKOFF_MS);
      timerRef.current = setTimeout(connect, delay);
    };
  }, []); // stable — uses refs

  useEffect(() => {
    if (enabled) {
      connect();
    } else {
      esRef.current?.close();
      esRef.current = null;
      if (timerRef.current) clearTimeout(timerRef.current);
    }

    return () => {
      esRef.current?.close();
      esRef.current = null;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [enabled, connect]);
}
