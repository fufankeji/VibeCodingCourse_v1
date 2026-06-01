import { API_BASE_URL } from './client';

export type SSEEventHandler = (event: string, data: Record<string, unknown>) => void;

export function subscribeSSE(sessionId: string, onEvent: SSEEventHandler): () => void {
  const url = `${API_BASE_URL}/sessions/${sessionId}/events`;
  let eventSource: EventSource | null = null;
  let closed = false;

  function connect() {
    if (closed) return;
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
      setTimeout(connect, 3000);
    };
  }

  connect();

  return () => {
    closed = true;
    eventSource?.close();
  };
}
