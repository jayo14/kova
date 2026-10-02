import type {
  Mission,
  MissionExecution,
  CreateMissionInput,
  UpdateMissionInput,
} from "@/lib/types";
import { api } from "./client";
import { mapKeysToSnake, stripNulls } from "./mappers";
import { getProjects } from "./projects";
import { normalizeExecutionStatus } from "@/lib/executions/status";

// ── Backend response shapes ───────────────────────────────

export interface BackendFlowStep {
  action: string;
  selector?: string | null;
  value?: string | null;
  credential_id?: string | null;
  description?: string | null;
}

export interface BackendFlow {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  persona: Record<string, unknown> | null;
  objective: string | null;
  steps: BackendFlowStep[];
  success_condition: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

import type { BackendExecution } from "./executions";
export type { BackendExecution };

// ── Mapping helpers ───────────────────────────────────────

function personaToString(
  persona: Record<string, unknown> | null
): string | null {
  if (!persona) return null;
  if (typeof persona === "string") return persona;
  return (persona.role as string) ?? JSON.stringify(persona);
}

function stepsToStrings(steps: BackendFlow["steps"]): BackendFlowStep[] {
  if (!Array.isArray(steps)) return [];
  return steps.map((s) => ({
    action: s.action,
    selector: s.selector ?? null,
    value: s.value ?? null,
    credential_id: s.credential_id ?? null,
    description: s.description ?? null,
  }));
}

export function backendToMission(
  flow: BackendFlow,
  projectName: string,
  projectUrl: string
): Mission {
  return {
    id: flow.id,
    projectId: flow.project_id,
    projectName,
    projectUrl,
    name: flow.name,
    description: flow.description ?? null,
    persona: personaToString(flow.persona),
    objective: flow.objective ?? flow.description ?? "",
    steps: stepsToStrings(flow.steps),
    // CRITICAL: success_condition is a structured verification object (e.g.
    // {"text_visible": "Dashboard"}). It must NEVER be stringified or unwrapped
    // into {description: ...} — the Verifier would see unknown keys and the
    // outcome would be unverifiable.
    successCondition: flow.success_condition ?? null,
    createdAt: flow.created_at,
    updatedAt: flow.updated_at,
  };
}

export function backendToExecution(ex: BackendExecution): MissionExecution {
  return {
    id: ex.id,
    missionId: ex.flow_id,
    status: normalizeExecutionStatus(ex.status),
    createdAt: ex.created_at,
  };
}

// ── Project cache (per request) ──────────────────────────

let projectCache: Map<string, { name: string; baseUrl: string }> | null = null;

async function getProjectMap(
  token?: string
): Promise<Map<string, { name: string; baseUrl: string }>> {
  if (projectCache) return projectCache;
  const projects = await getProjects(token);
  projectCache = new Map(
    projects.map((p) => [p.id, { name: p.name, baseUrl: p.baseUrl }])
  );
  return projectCache;
}

function resetProjectCache(): void {
  projectCache = null;
}

// ── Public API ────────────────────────────────────────────

export async function getMissions(
  projectId?: string,
  token?: string
): Promise<Mission[]> {
  const projectMap = await getProjectMap(token);

  const flows = projectId
    ? await api.get<BackendFlow[]>(
        `/api/v1/flows/?project_id=${encodeURIComponent(projectId)}`,
        token
      )
    : await fetchAllFlows(projectMap, token);

  return flows.map((f) => {
    const proj = projectMap.get(f.project_id);
    return backendToMission(
      f,
      proj?.name ?? "Unknown project",
      proj?.baseUrl ?? ""
    );
  });
}

async function fetchAllFlows(
  projectMap: Map<string, { name: string; baseUrl: string }>,
  token?: string
): Promise<BackendFlow[]> {
  const projectIds = Array.from(projectMap.keys());
  if (projectIds.length === 0) return [];

  const results = await Promise.all(
    projectIds.map((pid) =>
      api.get<BackendFlow[]>(
        `/api/v1/flows/?project_id=${encodeURIComponent(pid)}`,
        token
      ).catch(() => [])
    )
  );
  return results.flat();
}

export async function getMission(
  missionId: string,
  token?: string
): Promise<Mission | null> {
  if (!missionId) return null;
  const projectMap = await getProjectMap(token);
  try {
    const flow = await api.get<BackendFlow>(`/api/v1/flows/${encodeURIComponent(missionId)}`, token);
    const proj = projectMap.get(flow.project_id);
    return backendToMission(
      flow,
      proj?.name ?? "Unknown project",
      proj?.baseUrl ?? ""
    );
  } catch {
    return null;
  }
}

function formatStepForBackend(s: string | Record<string, unknown>): BackendFlowStep {
  if (typeof s === "object" && s !== null) {
    const obj = s as Record<string, unknown>;
    const actionStr = String(obj.action || obj.type || "click");
    const selectorVal = obj.selector || obj.target;
    let selectorStr: string | null = null;
    if (typeof selectorVal === "string" && selectorVal !== "[object Object]") {
      selectorStr = selectorVal;
    } else if (selectorVal && typeof (selectorVal as Record<string, unknown>).css === "string") {
      selectorStr = (selectorVal as Record<string, string>).css;
    }
    const val = obj.value || obj.url;
    const valStr = typeof val === "string" ? val : (val != null && val !== "[object Object]" ? String(val) : null);
    const descVal = obj.description || obj.name;
    const descStr = typeof descVal === "string" && descVal !== "[object Object]" ? descVal : null;

    return {
      action: actionStr,
      selector: selectorStr,
      value: valStr,
      credential_id: typeof obj.credential_id === "string" ? obj.credential_id : null,
      description: descStr,
    };
  }
  const strVal = String(s).trim();
  return {
    action: strVal,
    description: strVal,
  };
}

export async function createMission(
  input: CreateMissionInput,
  token?: string
): Promise<Mission> {
  resetProjectCache();
  const body = mapKeysToSnake({
    projectId: input.projectId,
    name: input.name.trim(),
    description: input.description?.trim() ?? null,
    persona: input.persona ? { role: input.persona.trim() } : null,
    objective: input.objective?.trim() || input.name.trim(),
    steps: (input.steps ?? []).map(formatStepForBackend),
    // Pass the structured condition through verbatim. Adding any wrapper here
    // (e.g. {description: ...}) breaks verification downstream.
    successCondition: input.successCondition ?? null,
  });

  const flow = await api.post<BackendFlow>("/api/v1/flows/", body, token);
  const proj = await getProjectMap(token);
  const p = proj.get(flow.project_id);
  return backendToMission(
    flow,
    p?.name ?? input.projectName,
    p?.baseUrl ?? input.projectUrl
  );
}

export async function updateMission(
  missionId: string,
  input: UpdateMissionInput,
  token?: string
): Promise<Mission | null> {
  if (!missionId) return null;
  resetProjectCache();

  const patch: Record<string, unknown> = {};
  if (input.name !== undefined) patch.name = input.name.trim();
  if (input.description !== undefined) {
    patch.description = input.description ? input.description.trim() : null;
  }
  if (input.persona !== undefined) {
    patch.persona = input.persona ? { role: input.persona.trim() } : null;
  }
  if (input.objective !== undefined) patch.objective = input.objective.trim();
  if (input.steps !== undefined) {
    patch.steps = input.steps.map(formatStepForBackend);
  }
  if (input.successCondition !== undefined) {
    // Structured pass-through — never wrap or stringify.
    patch.success_condition = input.successCondition ?? null;
  }

  const body = stripNulls(mapKeysToSnake(patch));
  try {
    const flow = await api.put<BackendFlow>(
      `/api/v1/flows/${encodeURIComponent(missionId)}`,
      body,
      token
    );
    const projectMap = await getProjectMap(token);
    const proj = projectMap.get(flow.project_id);
    return backendToMission(
      flow,
      proj?.name ?? "Unknown project",
      proj?.baseUrl ?? ""
    );
  } catch {
    return null;
  }
}

export async function deleteMission(missionId: string, token?: string): Promise<boolean> {
  if (!missionId) return false;
  try {
    await api.delete(`/api/v1/flows/${encodeURIComponent(missionId)}`, token);
    resetProjectCache();
    return true;
  } catch {
    return false;
  }
}

export async function getMissionExecutions(
  missionId: string,
  token?: string
): Promise<MissionExecution[]> {
  if (!missionId) return [];
  try {
    const execs = await api.get<BackendExecution[]>(
      `/api/v1/executions/?flow_id=${encodeURIComponent(missionId)}`,
      token
    );
    return execs
      .map(backendToExecution)
      .sort(
        (a, b) =>
          new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
      );
  } catch {
    return [];
  }
}

export async function runMission(
  missionId: string,
  token?: string
): Promise<MissionExecution | null> {
  if (!missionId) return null;
  try {
    const ex = await api.post<BackendExecution>(
      `/api/v1/flows/${encodeURIComponent(missionId)}/executions`,
      undefined,
      { token, timeoutMs: 30000 }
    );
    return backendToExecution(ex);
  } catch {
    return null;
  }
}
