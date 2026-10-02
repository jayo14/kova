import type { ExecutionStatus } from "@/lib/types";
import { getApiBaseUrl, getBrowserSessionToken } from "@/lib/api/client";
import { getExecution, getExecutionEvents } from "@/lib/api/executions";
import { isTerminalStatus, normalizeExecutionStatus } from "@/lib/executions/status";
import { validateExecutionEvent } from "@/lib/executions/event-mapper";
import type {
  ExecutionRealtimeHandlers,
  ExecutionStreamOptions,
  ExecutionStreamSubscription,
  StreamConnectionStatus,
} from "./types";

export * from "./types";

const DEFAULT_MAX_RECONNECT = 3;
const DEFAULT_INITIAL_BACKOFF_MS = 1000;
const DEFAULT_MAX_BACKOFF_MS = 5000;

/**
 * Subscribes to realtime updates for a single execution using Server-Sent Events (SSE).
 *
 * Guarantees:
 * - No access tokens leaked into URLs or query parameters.
 * - Automatic event validation and Chain of Thought suppression.
 * - Event deduplication by monotonic / UUID event ID.
 * - Bounded exponential backoff on disconnect.
 * - Authoritative HTTP state reconciliation upon reconnect.
 * - Automatic stream termination when terminal state is reached.
 * - Graceful fallback to static authoritative state when backend SSE is unavailable.
 */
export function subscribeToExecution(
  executionId: string,
  handlers: ExecutionRealtimeHandlers,
  options?: ExecutionStreamOptions
): ExecutionStreamSubscription {
  let isSubscribed = true;
  let connectionStatus: StreamConnectionStatus = "connecting";
  let reconnectAttempts = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let abortController: AbortController | null = null;
  const seenEventIds = new Set<string>();

  const maxReconnect = options?.maxReconnectAttempts ?? DEFAULT_MAX_RECONNECT;
  const initialBackoff = options?.initialBackoffMs ?? DEFAULT_INITIAL_BACKOFF_MS;
  const maxBackoff = options?.maxBackoffMs ?? DEFAULT_MAX_BACKOFF_MS;

  function updateStatus(newStatus: StreamConnectionStatus) {
    if (!isSubscribed || connectionStatus === newStatus) return;
    connectionStatus = newStatus;
    handlers.onConnectionChange?.(newStatus);
  }

  function handleTerminalState(status: ExecutionStatus) {
    handlers.onStatusChange?.(status);
    closeStream("terminal_state_reached");
  }

  function handleRawEventData(rawData: string) {
    if (!isSubscribed) return;

    try {
      const parsed = JSON.parse(rawData);
      const event = validateExecutionEvent(parsed);
      if (!event) return;

      // Event deduplication by ID
      if (seenEventIds.has(event.id)) {
        return;
      }
      seenEventIds.add(event.id);

      handlers.onEvent?.(event);

      // Check if event signals status transition
      if (event.eventType.startsWith("execution.")) {
        const subType = event.eventType.replace("execution.", "");
        const normalized = normalizeExecutionStatus(subType);
        handlers.onStatusChange?.(normalized);

        if (isTerminalStatus(normalized)) {
          handleTerminalState(normalized);
        }
      }
    } catch {
      // Ignore malformed event frames safely
    }
  }

  /**
   * Reconciles state against authoritative backend HTTP endpoints.
   */
  async function reconcileCurrentState() {
    if (!isSubscribed) return;

    try {
      let token = options?.token;
      if (!token && typeof window !== "undefined") {
        token = (await getBrowserSessionToken()) ?? undefined;
      }
      const [currentExec, existingEvents] = await Promise.all([
        getExecution(executionId, token),
        getExecutionEvents(executionId, token).catch(() => []),
      ]);

      if (!isSubscribed) return;

      if (currentExec) {
        handlers.onStatusChange?.(currentExec.status);
        if (isTerminalStatus(currentExec.status)) {
          handleTerminalState(currentExec.status);
          return;
        }
      }

      // Replay any events missed during disconnection
      for (const ev of existingEvents) {
        if (!seenEventIds.has(ev.id)) {
          seenEventIds.add(ev.id);
          handlers.onEvent?.(ev);
        }
      }
    } catch (err) {
      if (isSubscribed && err instanceof Error) {
        handlers.onError?.(err);
      }
    }
  }

  /**
   * Connects to the SSE stream endpoint.
   * If backend does not support SSE or returns 404, cleanly transitions to 'unavailable'.
   */
  async function connect() {
    if (!isSubscribed) return;

    abortController = new AbortController();
    updateStatus(reconnectAttempts > 0 ? "reconnecting" : "connecting");

    const baseUrl = getApiBaseUrl();
    const streamUrl = `${baseUrl}/api/v1/executions/${encodeURIComponent(executionId)}/events/stream`;

    try {
      // We use fetch with ReadableStream to support Authorization headers without URL leakage
      const headers: Record<string, string> = {
        Accept: "text/event-stream",
      };

      let token = options?.token;
      if (!token && typeof window !== "undefined") {
        token = (await getBrowserSessionToken()) ?? undefined;
      }

      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      const response = await fetch(streamUrl, {
        method: "GET",
        headers,
        signal: abortController.signal,
      });

      if (!isSubscribed) return;

      if (response.status === 404 || response.status === 501 || response.status === 405) {
        // Backend has not implemented the SSE stream endpoint yet.
        // Fall back gracefully as per Section 7 & 25 without breaking the UI.
        updateStatus("unavailable");
        await reconcileCurrentState();
        return;
      }

      if (!response.ok) {
        throw new Error(`SSE connection failed with status ${response.status}`);
      }

      if (!response.body) {
        throw new Error("No response body for SSE stream");
      }

      // Successful connection
      updateStatus("connected");
      reconnectAttempts = 0;
      handlers.onOpen?.();

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (isSubscribed) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split(/\r\n|\r|\n/);
        buffer = lines.pop() ?? "";

        let currentData = "";

        for (const line of lines) {
          if (line.startsWith("data:")) {
            currentData += line.slice(5).trim();
          } else if (line.startsWith("event: done")) {
            closeStream("server_closed");
            return;
          } else if (line === "" && currentData) {
            handleRawEventData(currentData);
            currentData = "";
          }
        }
      }
    } catch (err) {
      if (!isSubscribed) return;

      if ((err as Error).name === "AbortError") {
        return;
      }

      scheduleReconnect();
    }
  }

  function scheduleReconnect() {
    if (!isSubscribed) return;

    if (reconnectAttempts >= maxReconnect) {
      // Reconnect attempts exhausted — transition to unavailable and perform final sync
      updateStatus("unavailable");
      reconcileCurrentState();
      return;
    }

    reconnectAttempts++;
    updateStatus("reconnecting");

    const backoff = Math.min(
      initialBackoff * Math.pow(2, reconnectAttempts - 1),
      maxBackoff
    );

    reconnectTimer = setTimeout(async () => {
      if (!isSubscribed) return;
      await reconcileCurrentState();
      connect();
    }, backoff);
  }

  function closeStream(reason?: string) {
    if (!isSubscribed) return;
    isSubscribed = false;

    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }

    if (abortController) {
      abortController.abort();
      abortController = null;
    }

    connectionStatus = "closed";
    handlers.onConnectionChange?.("closed");
    handlers.onClose?.(reason);
  }

  // Start connection
  connect();

  return {
    executionId,
    unsubscribe: () => closeStream("client_unsubscribed"),
    getStatus: () => connectionStatus,
  };
}
