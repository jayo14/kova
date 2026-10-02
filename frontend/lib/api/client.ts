import { ApiError, isApiError } from "./errors";

export { ApiError, isApiError };

export interface RequestOptions {
  token?: string | null;
  timeoutMs?: number;
  isRetry?: boolean;
}

const DEFAULT_BASE_URL = "http://localhost:8000";
const DEFAULT_TIMEOUT_MS = 45000;

export function getApiBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_URL || DEFAULT_BASE_URL;
  return url.replace(/\/+$/, "");
}

export async function getBrowserSessionToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  try {
    const { createClient } = await import("@/lib/auth/client");
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();
    return session?.access_token ?? null;
  } catch {
    return null;
  }
}

async function refreshBrowserSession(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  try {
    const { createClient } = await import("@/lib/auth/client");
    const supabase = createClient();
    const {
      data: { session },
      error,
    } = await supabase.auth.refreshSession();
    if (error || !session) return null;
    return session.access_token ?? null;
  } catch {
    return null;
  }
}

export async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options?: RequestOptions | string
): Promise<T> {
  const normalizedOpts: RequestOptions =
    typeof options === "string"
      ? { token: options }
      : options ?? {};

  const timeoutMs = normalizedOpts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  let isTimerAborted = false;
  const timer = setTimeout(() => {
    isTimerAborted = true;
    controller.abort();
  }, timeoutMs);

  try {
    let authToken = normalizedOpts.token ?? null;

    // Client-side: resolve token from active Supabase session if not explicitly provided
    if (authToken === null && typeof window !== "undefined") {
      authToken = await getBrowserSessionToken();
    }

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json",
    };

    if (authToken) {
      headers["Authorization"] = `Bearer ${authToken}`;
    }

    const url = `${getApiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;

    const res = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });

    // 401 Unauthorized handling with single-retry token refresh guard
    if (res.status === 401 && typeof window !== "undefined" && !normalizedOpts.isRetry) {
      const refreshedToken = await refreshBrowserSession();
      if (refreshedToken) {
        clearTimeout(timer);
        return request<T>(method, path, body, {
          ...normalizedOpts,
          token: refreshedToken,
          isRetry: true,
        });
      }
    }

    if (!res.ok) {
      let message = `Request failed (${res.status})`;
      let details: unknown = undefined;

      try {
        const errorData = await res.json();
        details = errorData?.detail ?? errorData;
        if (typeof errorData?.detail === "string") {
          message = errorData.detail;
        } else if (typeof errorData?.message === "string") {
          message = errorData.message;
        }
      } catch {
        // Body was not JSON or empty
      }

      throw new ApiError({
        status: res.status,
        message,
        details,
      });
    }

    if (res.status === 204) {
      return undefined as T;
    }

    return (await res.json()) as T;
  } catch (err) {
    if ((err as Error).name === "AbortError") {
      if (isTimerAborted) {
        throw new ApiError({
          status: 0,
          message: "Request timed out",
        });
      }
      throw err;
    }
    if (isApiError(err)) {
      throw err;
    }
    if (err instanceof TypeError && (err.message.includes("fetch") || err.message.includes("network"))) {
      throw new ApiError({
        status: 0,
        message: "Unable to connect to Kova API server",
        details: err,
      });
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  get: <T>(path: string, options?: RequestOptions | string) =>
    request<T>("GET", path, undefined, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions | string) =>
    request<T>("POST", path, body, options),
  put: <T>(path: string, body?: unknown, options?: RequestOptions | string) =>
    request<T>("PUT", path, body, options),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions | string) =>
    request<T>("PATCH", path, body, options),
  delete: <T>(path: string, options?: RequestOptions | string) =>
    request<T>("DELETE", path, undefined, options),
};
