import type { ExecutionEvent, ExecutionStatus } from "@/lib/types";

export type StreamConnectionStatus =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "closed"
  | "unavailable";

export interface ExecutionRealtimeHandlers {
  /**
   * Called when a validated, sanitized ExecutionEvent arrives.
   */
  onEvent?: (event: ExecutionEvent) => void;

  /**
   * Called when the execution status changes (e.g., from 'running' to 'completed').
   */
  onStatusChange?: (status: ExecutionStatus) => void;

  /**
   * Called when the realtime stream successfully opens.
   */
  onOpen?: () => void;

  /**
   * Called when the realtime stream closes (e.g. upon reaching terminal state).
   */
  onClose?: (reason?: string) => void;

  /**
   * Called when an error occurs in the stream or transport.
   */
  onError?: (error: Error) => void;

  /**
   * Called whenever the stream connection status transitions.
   */
  onConnectionChange?: (status: StreamConnectionStatus) => void;
}

export interface ExecutionStreamOptions {
  /**
   * Maximum number of reconnection attempts before marking stream as unavailable.
   * Default: 3
   */
  maxReconnectAttempts?: number;

  /**
   * Initial backoff delay in milliseconds.
   * Default: 1000
   */
  initialBackoffMs?: number;

  /**
   * Maximum backoff delay in milliseconds.
   * Default: 5000
   */
  maxBackoffMs?: number;

  /**
   * Optional authentication token if stream uses Authorization header (e.g. via fetch-based SSE).
   */
  token?: string;
}

export interface ExecutionStreamSubscription {
  readonly executionId: string;
  unsubscribe: () => void;
  getStatus: () => StreamConnectionStatus;
}
