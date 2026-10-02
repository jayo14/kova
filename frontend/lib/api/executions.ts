import type {
  ExecutionDetail,
  ExecutionEvent,
  ExecutionListParams,
} from "@/lib/types";
import { api } from "./client";
import { mapKeysToCamel } from "./mappers";
import { normalizeExecutionStatus } from "@/lib/executions/status";

// ── Backend response shapes ───────────────────────────────

export interface BackendExecution {
  id: string;
  flow_id: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface BackendEvent {
  id: string;
  execution_id: string;
  event_type: string;
  payload: Record<string, unknown> | null;
  created_at: string;
}

interface BackendFlow {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
}

interface BackendProject {
  id: string;
  name: string;
  base_url: string;
}

// ── Enrichment cache ──────────────────────────────────────

let flowCache: Map<string, BackendFlow> | null = null;
let projectCache: Map<string, BackendProject> | null = null;

async function ensureCaches(): Promise<void> {
  flowCache = flowCache ?? new Map();
  projectCache = projectCache ?? new Map();
}

async function getFlowDetails(
  flowId: string,
  token?: string
): Promise<{ name: string; projectName: string; projectUrl: string }> {
  await ensureCaches();

  let flow = flowCache!.get(flowId);
  if (!flow) {
    try {
      flow = await api.get<BackendFlow>(`/api/v1/flows/${encodeURIComponent(flowId)}`, token);
      flowCache!.set(flowId, flow);
    } catch {
      return { name: "Unknown mission", projectName: "Unknown", projectUrl: "" };
    }
  }

  let project = projectCache!.get(flow.project_id);
  if (!project) {
    try {
      project = await api.get<BackendProject>(
        `/api/v1/projects/${encodeURIComponent(flow.project_id)}`,
        token
      );
      projectCache!.set(flow.project_id, project);
    } catch {
      return { name: flow.name, projectName: "Unknown", projectUrl: "" };
    }
  }

  return {
    name: flow.name,
    projectName: project.name,
    projectUrl: project.base_url,
  };
}

// ── Mapping ───────────────────────────────────────────────

export function backendToExecutionDetail(
  ex: BackendExecution,
  enrichment?: { name: string; projectName: string; projectUrl: string }
): ExecutionDetail {
  return {
    id: ex.id,
    missionId: ex.flow_id,
    missionName: enrichment?.name ?? "Unknown mission",
    projectName: enrichment?.projectName ?? "Unknown product",
    projectUrl: enrichment?.projectUrl ?? "",
    status: normalizeExecutionStatus(ex.status),
    createdAt: ex.created_at,
    startedAt: ex.started_at,
    completedAt: ex.completed_at,
    error: ex.error_message ?? null,
  };
}

export function backendToEvent(ev: BackendEvent): ExecutionEvent {
  const mapped = mapKeysToCamel(ev as unknown as Record<string, unknown>) as Record<string, unknown>;
  return {
    id: mapped.id as string,
    executionId: mapped.executionId as string,
    eventType: mapped.eventType as string,
    payload: (mapped.payload as Record<string, unknown>) ?? {},
    createdAt: mapped.createdAt as string,
  };
}

// ── Public API ────────────────────────────────────────────

export async function getExecutions(
  params?: ExecutionListParams,
  token?: string
): Promise<ExecutionDetail[]> {
  let path = "/api/v1/executions/";
  const queries: string[] = [];
  if (params?.missionId) {
    queries.push(`flow_id=${encodeURIComponent(params.missionId)}`);
  }
  if (queries.length > 0) {
    path += `?${queries.join("&")}`;
  }

  const execs = await api.get<BackendExecution[]>(path, token);

  const enriched = await Promise.all(
    execs.map(async (ex) => {
      const details = await getFlowDetails(ex.flow_id, token);
      return backendToExecutionDetail(ex, details);
    })
  );

  let results = enriched;

  if (params?.status) {
    const targetStatus = normalizeExecutionStatus(params.status);
    results = results.filter((ex) => ex.status === targetStatus);
  }

  if (params?.search) {
    const q = params.search.toLowerCase().trim();
    results = results.filter(
      (ex) =>
        ex.missionName.toLowerCase().includes(q) ||
        ex.projectName.toLowerCase().includes(q)
    );
  }

  return results.sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  );
}

export async function getExecution(
  executionId: string,
  token?: string
): Promise<ExecutionDetail | null> {
  if (!executionId) return null;
  try {
    const ex = await api.get<BackendExecution>(
      `/api/v1/executions/${encodeURIComponent(executionId)}`,
      token
    );
    const details = await getFlowDetails(ex.flow_id, token);
    return backendToExecutionDetail(ex, details);
  } catch (err: unknown) {
    const status = (err as { status?: number })?.status;
    if (status && status !== 404) {
      console.error(`[getExecution] Failed for ${executionId}: status=${status}`, err);
    }
    return null;
  }
}

export async function getExecutionEvents(
  executionId: string,
  token?: string
): Promise<ExecutionEvent[]> {
  if (!executionId) return [];
  try {
    const events = await api.get<BackendEvent[]>(
      `/api/v1/executions/${encodeURIComponent(executionId)}/events`,
      token
    );
    return events.map(backendToEvent);
  } catch {
    return [];
  }
}

export async function createExecution(
  missionId: string,
  token?: string
): Promise<ExecutionDetail | null> {
  if (!missionId) return null;
  try {
    const ex = await api.post<BackendExecution>(
      `/api/v1/flows/${encodeURIComponent(missionId)}/executions`,
      undefined,
      { token, timeoutMs: 30000 }
    );
    const details = await getFlowDetails(ex.flow_id, token);
    return backendToExecutionDetail(ex, details);
  } catch {
    return null;
  }
}

export async function runBatchExecutions(
  executionIds: string[],
  parallel: boolean = true,
  token?: string
): Promise<{ results: Array<{ execution_id: string; task_id: string }>; parallel: boolean; count: number } | null> {
  if (executionIds.length === 0) return null;
  try {
    const response = await api.post<{
      results: Array<{ execution_id: string; task_id: string }>;
      parallel: boolean;
      count: number;
    }>(
      "/api/v1/executions/batch",
      { execution_ids: executionIds, parallel },
      { token, timeoutMs: 30000 }
    );
    return response;
  } catch {
    return null;
  }
}

export async function cancelExecution(
  executionId: string,
  token?: string
): Promise<ExecutionDetail | null> {
  if (!executionId) return null;
  try {
    await api.post(
      `/api/v1/executions/${encodeURIComponent(executionId)}/cancel`,
      undefined,
      token
    );
    return await getExecution(executionId, token);
  } catch {
    return null;
  }
}
