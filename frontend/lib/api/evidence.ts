import { api, getApiBaseUrl } from "./client";
import { mapKeysToCamel } from "./mappers";

export type EvidenceType = "SCREENSHOT" | "VERIFICATION" | "ARTIFACT" | "VISUAL";

export type EvidenceStatus = "PENDING" | "UPLOADED" | "CAPTURED" | "VERIFIED" | "FAILED";

export interface Evidence {
  id: string;
  executionId: string;
  type: EvidenceType;
  title: string;
  purpose?: string | null;
  stepId?: string | null;
  kind?: "before" | "after" | "assertion" | "failure" | string | null;
  description?: string | null;
  status: EvidenceStatus;
  mimeType?: string | null;
  metadata?: Record<string, unknown>;
  createdAt: string;
  timestamp?: number | null;
  /** Short-lived signed URL or direct API URL for artifact access (screenshots only). */
  url?: string | null;
  domSnapshot?: string | null;
  a11yTree?: string | null;
  networkLog?: Array<Record<string, unknown>> | Record<string, unknown> | null;
  videoUrl?: string | null;
  traceUrl?: string | null;
  elementLocator?: string | null;
  timestampRange?: [number, number] | number[] | null;
  note?: string | null;
}

function formatEvidenceUrl(url: unknown): string | null {
  if (typeof url !== "string" || !url) return null;
  if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("data:")) {
    return url;
  }
  const base = getApiBaseUrl();
  return `${base}${url.startsWith("/") ? "" : "/"}${url}`;
}

function parseEvidenceItem(item: Record<string, unknown>): Evidence {
  const mapped = mapKeysToCamel(item) as Record<string, unknown>;
  const meta = (mapped.metadata as Record<string, unknown>) || {};
  return {
    id: mapped.id as string,
    executionId: mapped.executionId as string,
    type: mapped.type as EvidenceType,
    title: mapped.title as string,
    purpose: (mapped.purpose as string) || (meta.purpose as string) || (meta.checkpoint as string) || null,
    stepId: (mapped.stepId as string) || (meta.step_id as string) || (meta.stepId as string) || null,
    kind: (mapped.kind as string) || (meta.kind as string) || null,
    description: mapped.description as string | null | undefined,
    status: mapped.status as EvidenceStatus,
    mimeType: mapped.mimeType as string | null | undefined,
    metadata: meta,
    createdAt: mapped.createdAt as string,
    timestamp: (mapped.timestamp as number) || (meta.timestamp as number) || null,
    url: formatEvidenceUrl(mapped.url),
    domSnapshot: (mapped.domSnapshot as string) || null,
    a11yTree: (mapped.a11yTree as string) || null,
    networkLog: (mapped.networkLog as Array<Record<string, unknown>>) || null,
    videoUrl: formatEvidenceUrl(mapped.videoUrl),
    traceUrl: formatEvidenceUrl(mapped.traceUrl),
    elementLocator: (mapped.elementLocator as string) || null,
    timestampRange: (mapped.timestampRange as number[]) || null,
    note: (mapped.note as string) || null,
  };
}

/**
 * Fetch all evidence for an execution.
 * Returns evidence metadata with signed URLs for screenshot artifacts.
 */
export async function getExecutionEvidence(
  executionId: string,
  token?: string
): Promise<Evidence[]> {
  const raw = await api.get<unknown[]>(
    `/api/v1/executions/${executionId}/evidence`,
    { token }
  );
  return (raw as Record<string, unknown>[]).map(parseEvidenceItem);
}

/**
 * Fetch evidence grouped by step_id.
 */
export async function getGroupedExecutionEvidence(
  executionId: string,
  token?: string
): Promise<{ stepId: string; items: Evidence[] }[]> {
  const raw = await api.get<Array<{ step_id: string; items: Record<string, unknown>[] }>>(
    `/api/v1/executions/${executionId}/evidence?grouped=true`,
    { token }
  );
  return raw.map((group) => ({
    stepId: group.step_id,
    items: (group.items || []).map(parseEvidenceItem),
  }));
}

/**
 * Fetch a single evidence item by ID.
 */
export async function getEvidence(
  executionId: string,
  evidenceId: string,
  token?: string
): Promise<Evidence | null> {
  try {
    const raw = await api.get<unknown>(
      `/api/v1/executions/${executionId}/evidence/${evidenceId}`,
      { token }
    );
    return parseEvidenceItem(raw as Record<string, unknown>);
  } catch {
    return null;
  }
}

/**
 * Refresh the signed URL for an evidence item.
 * Returns a new signed URL or null on failure.
 */
export async function refreshEvidenceUrl(
  executionId: string,
  evidenceId: string,
  token?: string
): Promise<string | null> {
  try {
    const raw = await api.get<{ url?: string }>(
      `/api/v1/executions/${executionId}/evidence/${evidenceId}/refresh-url`,
      { token }
    );
    return formatEvidenceUrl(raw?.url) || null;
  } catch {
    return null;
  }
}
