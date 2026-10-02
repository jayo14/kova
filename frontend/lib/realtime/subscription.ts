import type { ExecutionDetail, ExecutionEvent, ActivityItem } from "@/lib/types";
import { mapExecutionEvents } from "@/lib/executions/event-mapper";
import { getExecution, getExecutionEvents } from "@/lib/api/executions";
import { subscribeToExecution as subscribeRealtime } from "./executions";
import type { StreamConnectionStatus } from "./types";

export interface ExecutionSubscription {
  executionId: string;
  unsubscribe: () => void;
  getStatus?: () => StreamConnectionStatus;
}

export interface ExecutionHandlers {
  onExecutionUpdate?: (execution: ExecutionDetail) => void;
  onEventsUpdate?: (
    events: ExecutionEvent[],
    activities: ActivityItem[]
  ) => void;
  onConnectionChange?: (status: StreamConnectionStatus) => void;
  onError?: (error: string) => void;
}

/**
 * Compatibility wrapper that bridges existing component callers to the
 * standardized SSE realtime execution subscription engine.
 */
export function subscribeToExecution(
  executionId: string,
  handlers: ExecutionHandlers
): ExecutionSubscription {
  const allEvents: ExecutionEvent[] = [];

  const sub = subscribeRealtime(executionId, {
    onEvent: (event) => {
      allEvents.push(event);
      const activities = mapExecutionEvents(allEvents);
      handlers.onEventsUpdate?.(allEvents, activities);
    },
    onStatusChange: (status) => {
      getExecution(executionId).then((exec) => {
        if (exec) {
          handlers.onExecutionUpdate?.({ ...exec, status });
        }
      });
    },
    onConnectionChange: (status) => {
      handlers.onConnectionChange?.(status);
    },
    onError: (err) => {
      handlers.onError?.(err.message);
    },
  });

  return {
    executionId,
    unsubscribe: sub.unsubscribe,
    getStatus: sub.getStatus,
  };
}

export async function fetchExecutionState(executionId: string): Promise<{
  execution: ExecutionDetail | null;
  events: ExecutionEvent[];
  activities: ActivityItem[];
}> {
  const execution = await getExecution(executionId);
  const events = await getExecutionEvents(executionId);
  const activities = mapExecutionEvents(events);
  return { execution, events, activities };
}
