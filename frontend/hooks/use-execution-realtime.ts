"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import type {
  ExecutionDetail,
  ExecutionEvent,
  ActivityItem,
  ExecutionStatus,
} from "@/lib/types";
import { isTerminalStatus } from "@/lib/executions/status";
import { mapExecutionEvents, deduplicateEvents } from "@/lib/executions/event-mapper";
import { getExecution, getExecutionEvents } from "@/lib/api/executions";
import {
  subscribeToExecution,
  type StreamConnectionStatus,
  type ExecutionStreamSubscription,
} from "@/lib/realtime/executions";

export interface UseExecutionRealtimeOptions {
  executionId: string;
  initialExecution: ExecutionDetail;
  initialEvents?: ExecutionEvent[];
  initialActivities?: ActivityItem[];
  enabled?: boolean;
  token?: string;
}

export interface UseExecutionRealtimeResult {
  execution: ExecutionDetail;
  events: ExecutionEvent[];
  activities: ActivityItem[];
  connectionStatus: StreamConnectionStatus;
  isConnected: boolean;
  isReconnecting: boolean;
  isStreamUnavailable: boolean;
  isTerminal: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  updateExecutionLocally: (updater: (prev: ExecutionDetail) => ExecutionDetail) => void;
}

/**
 * React hook that manages the lifecycle of an SSE execution stream subscription.
 * Handles mounting/unmounting, background tab visibility sync, terminal state freezing,
 * and presentation-safe activity timeline projection.
 */
export function useExecutionRealtime({
  executionId,
  initialExecution,
  initialEvents = [],
  initialActivities = [],
  enabled = true,
  token,
}: UseExecutionRealtimeOptions): UseExecutionRealtimeResult {
  const [execution, setExecution] = useState<ExecutionDetail>(initialExecution);
  const [events, setEvents] = useState<ExecutionEvent[]>(initialEvents);
  const [activities, setActivities] = useState<ActivityItem[]>(
    initialActivities.length > 0
      ? initialActivities
      : mapExecutionEvents(initialEvents)
  );
  const [streamStatus, setStreamStatus] =
    useState<StreamConnectionStatus>("connecting");
  const [error, setError] = useState<string | null>(null);

  const subRef = useRef<ExecutionStreamSubscription | null>(null);
  const isTerminal = isTerminalStatus(execution.status);
  const connectionStatus: StreamConnectionStatus =
    !enabled || isTerminal ? "closed" : streamStatus;

  // Manual or visibility-change refresh from authoritative HTTP
  const refresh = useCallback(async () => {
    try {
      const [freshExec, freshEvents] = await Promise.all([
        getExecution(executionId, token),
        getExecutionEvents(executionId, token).catch(() => []),
      ]);

      if (freshExec) {
        setExecution(freshExec);
      }

      if (freshEvents.length > 0) {
        setEvents((prev) => {
          const merged = deduplicateEvents([...prev, ...freshEvents]);
          setActivities(mapExecutionEvents(merged));
          return merged;
        });
      }
    } catch (err) {
      if (err instanceof Error) {
        setError(err.message);
      }
    }
  }, [executionId, token]);

  // Update local execution state (e.g. optimistic or action responses)
  const updateExecutionLocally = useCallback(
    (updater: (prev: ExecutionDetail) => ExecutionDetail) => {
      setExecution(updater);
    },
    []
  );

  useEffect(() => {
    if (!enabled || isTerminal) {
      return;
    }

    const sub = subscribeToExecution(
      executionId,
      {
        onEvent: (newEvent) => {
          setEvents((prev) => {
            const updated = deduplicateEvents([...prev, newEvent]);
            setActivities(mapExecutionEvents(updated));
            return updated;
          });
        },
        onStatusChange: (newStatus: ExecutionStatus) => {
          setExecution((prev) => {
            if (prev.status === newStatus) return prev;
            return { ...prev, status: newStatus };
          });

          if (isTerminalStatus(newStatus)) {
            refresh();
          }
        },
        onConnectionChange: (status) => {
          setStreamStatus(status);
        },
        onError: (err) => {
          setError(err.message);
        },
      },
      { token }
    );

    subRef.current = sub;

    return () => {
      sub.unsubscribe();
      subRef.current = null;
    };
  }, [executionId, enabled, isTerminal, token, refresh]);

  // Tab visibility change handler: reconcile state when tab becomes visible again
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible" && !isTerminal) {
        refresh();
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [isTerminal, refresh]);

  return {
    execution,
    events,
    activities,
    connectionStatus,
    isConnected: connectionStatus === "connected",
    isReconnecting: connectionStatus === "reconnecting",
    isStreamUnavailable: connectionStatus === "unavailable",
    isTerminal,
    error,
    refresh,
    updateExecutionLocally,
  };
}
