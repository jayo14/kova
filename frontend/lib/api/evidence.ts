import { api, getApiBaseUrl } from "./client";
import { mapKeysToCamel } from "./mappers";

export type EvidenceType = "SCREENSHOT" | "VERIFICATION" | "ARTIFACT";

export type EvidenceStatus = "CAPTURED" | "VERIFIED" | "FAILED";

export interface Evidence {
  id: string;
  executionId: string;
  type: EvidenceType;
  title: string;
  description?: string | null;
  status: EvidenceStatus;
  mimeType?: string | null;
  metadata?: Record<string, unknown>;
  createdAt: string;
  /** Short-lived signed URL or direct API URL for artifact access (screenshots only). */
  url?: string | null;
}

function formatEvidenceUrl(url: unknown): string | null {
  if (typeof url !== "string" || !url) return null;
  if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("data:")) {
    return url;
  }
  const base = getApiBaseUrl();
  return `${base}${url.startsWith("/") ? "" : "/"}${url}`;
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
  return (raw as Record<string, unknown>[]).map((item) => {
    const mapped = mapKeysToCamel(item) as Record<string, unknown>;
    return {
      id: mapped.id as string,
      executionId: mapped.executionId as string,
      type: mapped.type as EvidenceType,
      title: mapped.title as string,
      description: mapped.description as string | null | undefined,
      status: mapped.status as EvidenceStatus,
      mimeType: mapped.mimeType as string | null | undefined,
      metadata: mapped.metadata as Record<string, unknown> | undefined,
      createdAt: mapped.createdAt as string,
      url: formatEvidenceUrl(mapped.url),
    } satisfies Evidence;
  });
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
    const mapped = mapKeysToCamel(raw as Record<string, unknown>) as Record<string, unknown>;
    return {
      id: mapped.id as string,
      executionId: mapped.executionId as string,
      type: mapped.type as EvidenceType,
      title: mapped.title as string,
      description: mapped.description as string | null | undefined,
      status: mapped.status as EvidenceStatus,
      mimeType: mapped.mimeType as string | null | undefined,
      metadata: mapped.metadata as Record<string, unknown> | undefined,
      createdAt: mapped.createdAt as string,
      url: formatEvidenceUrl(mapped.url),
    } satisfies Evidence;
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
