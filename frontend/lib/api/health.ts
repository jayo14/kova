import { api, getApiBaseUrl } from "./client";
import { getErrorMessage } from "./errors";

export interface HealthCheckResponse {
  status: string;
  environment: string;
}

export interface HealthStatus {
  ok: boolean;
  status?: string;
  environment?: string;
  latencyMs?: number;
  baseUrl: string;
  error?: string;
}

/**
 * Checks connectivity to the Kova FastAPI backend.
 * Uses a tight 5-second timeout and measures roundtrip latency.
 */
export async function checkBackendHealth(timeoutMs = 5000): Promise<HealthStatus> {
  const baseUrl = getApiBaseUrl();
  const startTime = Date.now();

  try {
    const data = await api.get<HealthCheckResponse>("/api/v1/health", {
      timeoutMs,
    });

    const latencyMs = Date.now() - startTime;

    return {
      ok: data?.status === "ok",
      status: data?.status ?? "unknown",
      environment: data?.environment ?? "unknown",
      latencyMs,
      baseUrl,
    };
  } catch (err) {
    const latencyMs = Date.now() - startTime;
    return {
      ok: false,
      latencyMs,
      baseUrl,
      error: getErrorMessage(err, "Backend health check failed"),
    };
  }
}
