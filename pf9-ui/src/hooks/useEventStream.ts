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
  source?: 'live_event' | 'incident_brief';
  analysis?: string;
  recommendation?: string;
  runbook_name?: string;
  risk_level?: string;
}

type IncidentBriefPayload = {
  id?: number;
  event_id?: number;
  event_type?: string;
  severity?: string;
  risk_level?: string;
  entity_name?: string;
  analysis?: string;
  recommendation?: string;
  runbook_name?: string | null;
  generated_at?: string;
};

interface Options {
  /** Invoked for every event received from the stream. */
  onEvent: (event: LiveEvent) => void;
  /** Whether the stream should be open.  Defaults to true. */
  enabled?: boolean;
}

const _API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? '';
const _MAX_BACKOFF_MS = 30_000;

function _normalizeLiveEvent(raw: unknown): LiveEvent | null {
  if (!raw || typeof raw !== 'object') return null;
  const data = raw as Record<string, unknown>;

  if (typeof data.type === 'string' && data.type !== 'incident_brief') {
    return {
      id: typeof data.id === 'number' ? data.id : Date.now(),
      type: String(data.type || 'event'),
      title: String(data.title || data.type || 'Event'),
      severity:
        data.severity === 'critical'
          ? 'critical'
          : data.severity === 'warning'
          ? 'warning'
          : 'info',
      category: String(data.category || 'operational'),
      entity_type: String(data.entity_type || 'resource'),
      entity_id: String(data.entity_id || ''),
      occurred_at: String(data.occurred_at || new Date().toISOString()),
      source: 'live_event',
    };
  }

  const brief = data as IncidentBriefPayload;
  const risk = String(brief.risk_level || brief.severity || 'info').toLowerCase();
  const sev = risk === 'critical' ? 'critical' : risk === 'high' || risk === 'warning' ? 'warning' : 'info';
  const title = brief.event_type ? `AI Brief: ${brief.event_type}` : 'AI Incident Brief';
  return {
    id: typeof brief.id === 'number' ? brief.id : Date.now(),
    type: 'incident_brief',
    title,
    severity: sev,
    category: 'copilot',
    entity_type: brief.entity_name ? 'entity' : 'incident',
    entity_id: String(brief.event_id || brief.id || ''),
    occurred_at: String(brief.generated_at || new Date().toISOString()),
    source: 'incident_brief',
    analysis: brief.analysis,
    recommendation: brief.recommendation,
    runbook_name: brief.runbook_name || undefined,
    risk_level: risk,
  };
}

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
        const event = _normalizeLiveEvent(JSON.parse(e.data as string));
        if (!event) return;
        if (event.type === 'system') return; // internal/diagnostic events
        onEventRef.current(event);
        backoffRef.current = 1_000; // reset back-off on successful message
      } catch {
        // Ignore malformed JSON
      }
    };

    es.addEventListener('incident_brief', (e: Event) => {
      try {
        const msg = e as MessageEvent;
        const event = _normalizeLiveEvent(JSON.parse(msg.data as string));
        if (!event) return;
        onEventRef.current(event);
        backoffRef.current = 1_000;
      } catch {
        // Ignore malformed JSON
      }
    });

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
