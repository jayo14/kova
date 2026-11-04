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

export interface ReadyCheckResponse {
  status: "ok" | "degraded";
  postgres: { status: string; error?: string };
  redis: { status: string; tls_mode: string; error?: string };
  worker: { status: string; count: number; message?: string; queue_depths?: Record<string, number | null> };
}

/**
 * Checks readiness telemetry from the Kova backend (/ready).
 * Returns Postgres, Redis (with TLS mode), and honest worker status.
 */
export async function checkBackendReadiness(timeoutMs = 5000): Promise<ReadyCheckResponse | null> {
  const baseUrl = getApiBaseUrl();
  try {
    const res = await fetch(`${baseUrl}/ready`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
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
