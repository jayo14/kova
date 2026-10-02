import type { PendingIntent } from "@/lib/types";

const PENDING_INTENT_KEY = "kova_pending_intent";

/**
 * Safely parse and sanitize a target product URL without retaining credentials or scripts.
 */
function sanitizeProductUrl(rawUrl: string): string | null {
  const trimmed = rawUrl.trim();
  if (!trimmed) return null;
  if (/^javascript:/i.test(trimmed)) return null;

  try {
    const formatted = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
    const parsed = new URL(formatted);
    // Disallow embedding usernames or passwords in product URLs
    parsed.username = "";
    parsed.password = "";
    return parsed.toString();
  } catch {
    return null;
  }
}

/**
 * Save pending product intent in browser session storage.
 */
export function savePendingIntent(intent: PendingIntent): void {
  if (typeof window === "undefined") return;

  const sanitizedUrl = sanitizeProductUrl(intent.url);
  if (!sanitizedUrl) return;

  const safeIntent: PendingIntent = {
    url: sanitizedUrl,
    instruction: intent.instruction ? intent.instruction.slice(0, 500).trim() : undefined,
  };

  try {
    sessionStorage.setItem(PENDING_INTENT_KEY, JSON.stringify(safeIntent));
  } catch {
    // Session storage unavailable
  }
}

/**
 * Retrieve pending product intent from browser session storage.
 */
export function getPendingIntent(): PendingIntent | null {
  if (typeof window === "undefined") return null;

  try {
    const item = sessionStorage.getItem(PENDING_INTENT_KEY);
    if (!item) return null;
    const parsed = JSON.parse(item) as PendingIntent;
    if (!parsed.url) return null;

    const sanitizedUrl = sanitizeProductUrl(parsed.url);
    if (!sanitizedUrl) return null;

    return {
      url: sanitizedUrl,
      instruction: parsed.instruction,
    };
  } catch {
    return null;
  }
}

/**
 * Clear pending intent from storage after successful resolution.
 */
export function clearPendingIntent(): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.removeItem(PENDING_INTENT_KEY);
  } catch {
    // Session storage unavailable
  }
}

/**
 * Extract pending intent from query parameters (e.g. ?url=...&intent=...)
 */
export function getPendingIntentFromParams(
  searchParams: { get: (name: string) => string | null }
): PendingIntent | null {
  const urlParam = searchParams.get("url");
  if (!urlParam) return null;

  const sanitizedUrl = sanitizeProductUrl(urlParam);
  if (!sanitizedUrl) return null;

  const instruction =
    searchParams.get("intent") ||
    searchParams.get("workflow") ||
    searchParams.get("instruction") ||
    undefined;

  return {
    url: sanitizedUrl,
    instruction: instruction || undefined,
  };
}

/**
 * Format destination URL for returning to exploration experience with intact intent.
 */
export function buildExploreDestination(intent: PendingIntent): string {
  const params = new URLSearchParams();
  params.set("url", intent.url);
  if (intent.instruction) {
    params.set("intent", intent.instruction);
  }
  return `/explore?${params.toString()}`;
}
