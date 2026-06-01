import { API_BASE_URL } from './client';

export type SSEEventHandler = (event: string, data: Record<string, unknown>) => void;

export function subscribeSSE(sessionId: string, onEvent: SSEEventHandler): () => void {
  const url = `${API_BASE_URL}/sessions/${sessionId}/events`;
  let eventSource: EventSource | null = null;
  let retryTimer: number | null = null;
  let abortController: AbortController | null = null;
  let closed = false;

  function scheduleReconnect() {
    if (closed) return;
    if (retryTimer !== null) return;
    retryTimer = window.setTimeout(() => {
      retryTimer = null;
      void connect();
    }, 3000);
  }

  async function connect() {
    if (closed) return;

    abortController = new AbortController();
    try {
      const sessionRes = await fetch(`${API_BASE_URL}/sessions/${sessionId}`, {
        method: 'GET',
        signal: abortController.signal,
      });
      if (closed) return;
      if (sessionRes.status === 404) {
        closed = true;
        onEvent('session_not_found', { session_id: sessionId });
        return;
      }
      if (!sessionRes.ok) {
        scheduleReconnect();
        return;
      }
    } catch {
      if (!closed) scheduleReconnect();
      return;
    }

    eventSource = new EventSource(url);

    eventSource.onopen = () => {
      console.log(`[SSE] Connected to session ${sessionId}`);
    };

    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        onEvent('message', data);
      } catch {
        // ignore non-JSON messages
      }
    };

    // Listen for specific named events
    const eventTypes = [
      'connected', 'state_changed', 'scan_progress',
      'route_auto_passed', 'route_batch_review', 'route_interrupted',
      'item_decision_saved', 'report_generation_started', 'report_ready',
      'parse_started', 'parse_progress', 'parse_failed', 'parse_timeout',
      'system_failure', 'session_aborted',
    ];

    for (const type of eventTypes) {
      eventSource.addEventListener(type, (e: Event) => {
        const msgEvent = e as MessageEvent;
        try {
          const data = JSON.parse(msgEvent.data);
          onEvent(type, data);
        } catch {
          onEvent(type, {});
        }
      });
    }

    eventSource.onerror = () => {
      if (closed) return;
      console.warn('[SSE] Connection error, reconnecting in 3s...');
      eventSource?.close();
      scheduleReconnect();
    };
  }

  void connect();

  return () => {
    closed = true;
    abortController?.abort();
    if (retryTimer !== null) {
      window.clearTimeout(retryTimer);
      retryTimer = null;
    }
    eventSource?.close();
  };
}
