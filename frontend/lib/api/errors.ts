/**
 * Normalized API Error system for Kova frontend.
 * Provides unified error classification, FastAPI validation error formatting,
 * and safe, human-readable user error messages.
 */

export interface ApiErrorOptions {
  status: number;
  message: string;
  code?: string;
  details?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly details?: unknown;

  constructor(options: ApiErrorOptions) {
    super(options.message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.details = options.details;

    // Ensure proper prototype chain for instanceof checks
    Object.setPrototypeOf(this, ApiError.prototype);
  }
}

/**
 * Type guard to check if an unknown error is an ApiError.
 */
export function isApiError(err: unknown): err is ApiError {
  return (
    err instanceof ApiError ||
    (typeof err === "object" &&
      err !== null &&
      "name" in err &&
      (err as { name: unknown }).name === "ApiError" &&
      "status" in err &&
      typeof (err as { status: unknown }).status === "number")
  );
}

/**
 * Parses FastAPI validation errors (e.g., [{ loc: ["body", "name"], msg: "..." }])
 * or generic error detail objects into a clean, human-readable string.
 */
export function formatFastApiDetail(detail: unknown): string | null {
  if (!detail) return null;

  if (typeof detail === "string") {
    return detail.trim();
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (typeof item === "object" && item !== null) {
          const loc = Array.isArray((item as Record<string, unknown>).loc)
            ? (item as { loc: unknown[] }).loc
                .filter((part) => part !== "body" && part !== "query")
                .join(".")
            : "";
          const msg = (item as Record<string, unknown>).msg as string | undefined;
          if (loc && msg) return `${loc}: ${msg}`;
          if (msg) return msg;
        }
        return null;
      })
      .filter(Boolean);

    if (messages.length > 0) {
      return messages.join("; ");
    }
  }

  if (typeof detail === "object" && detail !== null) {
    const msg = (detail as Record<string, unknown>).message || (detail as Record<string, unknown>).msg;
    if (typeof msg === "string") return msg;
  }

  return null;
}

/**
 * Maps any error or HTTP status code to a safe, user-friendly message.
 */
export function getErrorMessage(err: unknown, fallback = "An unexpected error occurred."): string {
  if (isApiError(err)) {
    // 0 represents network failure, abort, or offline
    if (err.status === 0) {
      return "Unable to connect to Kova. Please check your connection.";
    }

    if (err.status === 401) {
      return "Session expired. Please sign in again.";
    }

    if (err.status === 403) {
      return "You do not have permission to perform this action.";
    }

    if (err.status === 404) {
      return err.message && err.message !== "Request failed (404)"
        ? err.message
        : "The requested resource was not found.";
    }

    if (err.status === 409) {
      return err.message && err.message !== "Request failed (409)"
        ? err.message
        : "A conflict occurred. The resource may already exist.";
    }

    if (err.status === 422) {
      const parsedDetail = formatFastApiDetail(err.details);
      if (parsedDetail) return parsedDetail;
      return err.message && err.message !== "Request failed (422)"
        ? err.message
        : "Invalid data provided. Please check your inputs.";
    }

    if (err.status >= 500) {
      return "A server error occurred. Please try again later.";
    }

    return err.message || fallback;
  }

  if (err instanceof Error) {
    if (err.name === "AbortError") {
      return "Request timed out. Please try again.";
    }
    return err.message || fallback;
  }

  return fallback;
}
