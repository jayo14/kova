/**
 * Map raw Supabase, HTTP, or FastAPI errors into calm, user-friendly messages.
 * Never leaks stack traces, internal IDs, or raw JSON.
 */
export function formatAuthError(error: unknown): string {
  if (!error) return "Something went wrong. Try again.";

  const message =
    typeof error === "string"
      ? error
      : error instanceof Error
        ? error.message
        : typeof error === "object" && error !== null && "message" in error
          ? String((error as { message: unknown }).message)
          : "";

  const lower = message.toLowerCase();

  if (
    lower.includes("invalid login credentials") ||
    lower.includes("invalid_grant") ||
    lower.includes("invalid email or password")
  ) {
    return "Incorrect email or password.";
  }

  if (
    lower.includes("user already registered") ||
    lower.includes("already registered") ||
    lower.includes("already exists") ||
    lower.includes("user_already_exists")
  ) {
    return "An account with this email already exists.";
  }

  if (
    lower.includes("password should be at least") ||
    lower.includes("weak_password") ||
    lower.includes("password is too short")
  ) {
    return "Password must be at least 6 characters.";
  }

  if (
    lower.includes("network") ||
    lower.includes("fetch failed") ||
    lower.includes("failed to fetch") ||
    lower.includes("timeout") ||
    lower.includes("connection refused")
  ) {
    return "Something went wrong while connecting. Try again.";
  }

  if (lower.includes("email not confirmed")) {
    return "Please confirm your email address before signing in.";
  }

  if (lower.includes("rate limit") || lower.includes("too many requests")) {
    return "Too many attempts. Please wait a moment and try again.";
  }

  return "Something went wrong. Try again.";
}
