import { request } from "./client";

export interface UsageSummary {
  executions_this_month: number;
  executions_limit: number;
  executions_remaining: number;
  evidence_storage_mb: number;
  evidence_storage_limit_mb: number;
  plan: string;
  period_start?: string | null;
  period_end?: string | null;
}

export async function getUsage(orgId?: string): Promise<UsageSummary> {
  const query = orgId ? `?org_id=${encodeURIComponent(orgId)}` : "";
  return request<UsageSummary>("GET", `/api/v1/usage${query}`);
}
