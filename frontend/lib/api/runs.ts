/**
 * API client for Run Orchestration endpoints (/api/v1/runs).
 */

import { api, getApiBaseUrl, getBrowserSessionToken } from "./client";

export interface RunExecutionItem {
  id: string;
  flowId?: string | null;
  missionName?: string | null;
  status: string;
  errorCode?: string | null;
  errorMessage?: string | null;
  createdAt?: string | null;
  completedAt?: string | null;
  durationMs?: number | null;
  stepProgress?: string | null;
}

export interface RunSummary {
  total: number;
  queued: number;
  running: number;
  passed: number;
  failed: number;
  blocked: number;
  unverified?: number;
  durationMs?: number;
}

export interface RunDetail {
  id: string;
  projectId: string;
  status: string;
  summary: RunSummary;
  progress: number;
  createdAt?: string | null;
  completedAt?: string | null;
  executions: RunExecutionItem[];
}

export interface RunCreatePayload {
  projectId: string;
  executionIds: string[];
  concurrencyLimit?: number;
  parallel?: boolean;
}

export async function createRun(
  payload: RunCreatePayload,
  token?: string
): Promise<{ id: string; status: string; summary: RunSummary }> {
  const data = await api.post<{
    id: string;
    project_id: string;
    status: string;
    summary: RunSummary;
    execution_ids: string[];
  }>(
    "/api/v1/runs",
    {
      project_id: payload.projectId,
      execution_ids: payload.executionIds,
      concurrency_limit: payload.concurrencyLimit ?? 2,
      parallel: payload.parallel ?? true,
    },
    token
  );

  return {
    id: data.id,
    status: data.status,
    summary: data.summary,
  };
}

export async function getRun(runId: string, token?: string): Promise<RunDetail> {
  const data = await api.get<{
    id: string;
    project_id: string;
    status: string;
    summary: RunSummary;
    progress: number;
    created_at?: string | null;
    completed_at?: string | null;
    executions: Array<{
      id: string;
      flow_id?: string | null;
      mission_name?: string | null;
      status: string;
      error_code?: string | null;
      error_message?: string | null;
      created_at?: string | null;
      completed_at?: string | null;
      duration_ms?: number | null;
      step_progress?: string | null;
    }>;
  }>(`/api/v1/runs/${encodeURIComponent(runId)}`, token);

  return {
    id: data.id,
    projectId: data.project_id,
    status: data.status,
    summary: data.summary,
    progress: data.progress,
    createdAt: data.created_at,
    completedAt: data.completed_at,
    executions: (data.executions || []).map((ex) => ({
      id: ex.id,
      flowId: ex.flow_id,
      missionName: ex.mission_name,
      status: ex.status,
      errorCode: ex.error_code,
      errorMessage: ex.error_message,
      createdAt: ex.created_at,
      completedAt: ex.completed_at,
      durationMs: ex.duration_ms,
      stepProgress: ex.step_progress,
    })),
  };
}

export async function cancelRun(runId: string, token?: string): Promise<RunDetail> {
  const data = await api.post<{
    id: string;
    project_id: string;
    status: string;
    summary: RunSummary;
    progress: number;
    created_at?: string | null;
    completed_at?: string | null;
    executions: Array<{
      id: string;
      flow_id?: string | null;
      mission_name?: string | null;
      status: string;
      error_code?: string | null;
      errorMessage?: string | null;
      error_message?: string | null;
      created_at?: string | null;
      completed_at?: string | null;
      duration_ms?: number | null;
      step_progress?: string | null;
    }>;
  }>(`/api/v1/runs/${encodeURIComponent(runId)}/cancel`, {}, token);

  return {
    id: data.id,
    projectId: data.project_id,
    status: data.status,
    summary: data.summary,
    progress: data.progress,
    createdAt: data.created_at,
    completedAt: data.completed_at,
    executions: (data.executions || []).map((ex) => ({
      id: ex.id,
      flowId: ex.flow_id,
      missionName: ex.mission_name,
      status: ex.status,
      errorCode: ex.error_code,
      errorMessage: ex.error_message || ex.errorMessage,
      createdAt: ex.created_at,
      completedAt: ex.completed_at,
      durationMs: ex.duration_ms,
      stepProgress: ex.step_progress,
    })),
  };
}

export interface RunControlStatus {
  run_id: string;
  state?: string;
  status?: string;
  executions?: Record<string, any>;
  active_executions?: number;
  paused_executions?: number;
  resumed_executions?: number;
}

export async function pauseRun(
  runId: string,
  reason?: string,
  token?: string
): Promise<RunControlStatus> {
  return await api.post<RunControlStatus>(
    `/api/v1/runs/${encodeURIComponent(runId)}/pause`,
    { reason },
    token
  );
}

export async function resumeRun(runId: string, token?: string): Promise<RunControlStatus> {
  return await api.post<RunControlStatus>(`/api/v1/runs/${encodeURIComponent(runId)}/resume`, {}, token);
}

export async function getRunControl(runId: string, token?: string): Promise<RunControlStatus> {
  return await api.get<RunControlStatus>(`/api/v1/runs/${encodeURIComponent(runId)}/control`, token);
}


export interface RunStreamHandlers {
  onUpdate?: (update: {
    status: string;
    progress: number;
    summary: RunSummary;
    executions: Array<{ id: string; status: string; errorCode?: string; errorMessage?: string }>;
  }) => void;
  onDone?: () => void;
  onError?: (err: Error) => void;
}

export function streamRunEvents(
  runId: string,
  handlers: RunStreamHandlers,
  token?: string
): () => void {
  const abortController = new AbortController();
  let isSubscribed = true;

  async function connect() {
    try {
      const baseUrl = getApiBaseUrl();
      const streamUrl = `${baseUrl}/api/v1/runs/${encodeURIComponent(runId)}/events/stream`;

      let authToken = token;
      if (!authToken && typeof window !== "undefined") {
        authToken = (await getBrowserSessionToken()) ?? undefined;
      }

      const headers: Record<string, string> = {
        Accept: "text/event-stream",
      };
      if (authToken) {
        headers["Authorization"] = `Bearer ${authToken}`;
      }

      const res = await fetch(streamUrl, {
        method: "GET",
        headers,
        signal: abortController.signal,
      });

      if (!res.ok || !res.body) {
        handlers.onError?.(new Error(`Failed to stream run events (${res.status})`));
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentData = "";

      while (isSubscribed) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split(/\r\n|\r|\n/);
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (line.startsWith("data:")) {
            currentData += line.slice(5).trim();
          } else if (line.startsWith("event: done")) {
            handlers.onDone?.();
            return;
          } else if (line === "" && currentData) {
            try {
              const parsed = JSON.parse(currentData);
              handlers.onUpdate?.(parsed);
            } catch {
              // ignore malformed frame
            }
            currentData = "";
          }
        }
      }
    } catch (err) {
      if (isSubscribed && (err as Error).name !== "AbortError") {
        handlers.onError?.(err as Error);
      }
    }
  }

  connect();

  return () => {
    isSubscribed = false;
    abortController.abort();
  };
}
