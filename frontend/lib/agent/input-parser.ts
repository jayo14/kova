export interface KovaIntent {
  rawInput: string;
  url: string | null;
  goal: string | null;
  instruction?: string;
  raw?: string;
  projectId?: string;
}

/**
 * Validates whether a string has a valid HTTP/HTTPS URL format.
 */
function isValidHttpUrl(stringUrl: string): boolean {
  try {
    const parsed = new URL(stringUrl);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * Checks if a token appears to be a domain, IP, localhost, or URL.
 */
function looksLikeUrl(token: string): boolean {
  const trimmed = token.trim();
  if (/^https?:\/\//i.test(trimmed)) return true;

  // Localhost with optional port and path
  if (/^localhost(?::\d+)?(?:\/.*)?$/i.test(trimmed)) return true;

  // IPv4 address with optional port and path
  if (/^(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?:\/.*)?$/.test(trimmed)) return true;

  // Domain with at least one dot and valid TLD-like suffix
  if (/^[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}(?::\d+)?(?:\/.*)?$/.test(trimmed)) {
    return true;
  }

  return false;
}

/**
 * Normalizes a URL:
 * - Prepends http:// for localhost/127.0.0.1 if missing, https:// for others.
 * - Preserves explicit trailing slash if present in raw candidate.
 * - Strips redundant trailing slash only if the raw candidate didn't have one.
 * - Preserves explicit paths, query parameters, and fragments.
 */
export function normalizeUrl(rawUrl: string): string | null {
  const trimmed = rawUrl.trim();
  if (!trimmed) return null;

  // Reject unsupported protocols (e.g. javascript:, file://, mailto:)
  // Note: host:port like localhost:3000 has digits after the colon, which is not a scheme.
  const schemeMatch = trimmed.match(/^([a-zA-Z][a-zA-Z0-9+.-]*):(?!\d)/);
  if (schemeMatch) {
    const scheme = schemeMatch[1].toLowerCase();
    if (scheme !== "http" && scheme !== "https") {
      return null;
    }
  }

  let candidate = trimmed;
  const hadTrailingSlash = candidate.endsWith("/");

  if (!/^https?:\/\//i.test(candidate)) {
    if (/^(?:localhost|127\.0\.0\.1)(?::\d+)?(?:\/.*)?$/i.test(candidate)) {
      candidate = `http://${candidate}`;
    } else {
      candidate = `https://${candidate}`;
    }
  }

  if (!isValidHttpUrl(candidate)) {
    return null;
  }

  try {
    const parsed = new URL(candidate);
    // If root domain without path/query/hash
    if (parsed.pathname === "/" && !parsed.search && !parsed.hash) {
      if (hadTrailingSlash) {
        return `${parsed.protocol}//${parsed.host}/`;
      }
      return `${parsed.protocol}//${parsed.host}`;
    }
    return parsed.href;
  } catch {
    return null;
  }
}

/**
 * Normalizes a hostname or URL by stripping leading www. and protocol/ports.
 */
export function normalizeHostname(urlOrHost: string): string {
  let host = urlOrHost.trim().toLowerCase();
  if (/^https?:\/\//i.test(host)) {
    try {
      host = new URL(host).hostname.toLowerCase();
    } catch {
      host = host.replace(/^https?:\/\//i, "").split("/")[0].split(":")[0];
    }
  } else {
    host = host.split("/")[0].split(":")[0];
  }
  return host.replace(/^www\d*\./i, "");
}

/**
 * Extracts a human-friendly project/brand name from a URL or hostname.
 * Handles www, subdomains, kebab-case, and special casing (e.g. SummaStudy).
 */
export function extractProjectName(urlOrHost: string): string {
  const host = normalizeHostname(urlOrHost);
  if (!host) return "Project";
  if (host === "localhost" || host === "127.0.0.1") return "Localhost";

  const parts = host.split(".");
  const genericPrefixes = new Set([
    "app", "web", "staging", "dev", "api", "auth", "admin", "beta", "m", "portal", "dashboard", "preview"
  ]);

  while (parts.length > 2 && genericPrefixes.has(parts[0])) {
    parts.shift();
  }

  const brandPart = parts[0] || "Project";

  // Handle known brands for accurate title-casing
  if (brandPart.toLowerCase() === "summastudy") {
    return "SummaStudy";
  }

  // Handle kebab-case or snake_case: "my-cool-site" -> "My Cool Site"
  const words = brandPart.split(/[-_]/).filter(Boolean);
  if (words.length > 1) {
    return words.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
  }

  return brandPart.charAt(0).toUpperCase() + brandPart.slice(1);
}

/**
 * Strips surrounding quotation marks from text if paired.
 */
function stripQuotes(str: string): string {
  const trimmed = str.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'")) ||
    (trimmed.startsWith("“") && trimmed.endsWith("”"))
  ) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

/**
 * Canonical parser for user input.
 * Extracts a canonical target URL and an optional goal/instruction.
 * Natural-language-only queries are preserved as a goal with url: null.
 */
export function parseKovaInput(rawInput: string): KovaIntent {
  const trimmed = rawInput.trim();
  if (!trimmed) {
    return {
      rawInput: "",
      url: null,
      goal: null,
      instruction: undefined,
      raw: "",
    };
  }

  function buildIntent(url: string | null, goal: string | null): KovaIntent {
    return {
      rawInput: trimmed,
      url,
      goal: goal || null,
      instruction: goal || undefined,
      raw: trimmed,
    };
  }

  // 1. Check for intentional separation via em-dash, en-dash, or spaced hyphen:
  const delimiterMatch = trimmed.match(/^(\S+?)\s*(?:[—–]|\s+--\s+|\s+-\s+)\s*(.+)$/);
  if (delimiterMatch) {
    const candidateUrlPart = delimiterMatch[1].trim();
    const candidateGoalPart = stripQuotes(delimiterMatch[2].trim());

    if (looksLikeUrl(candidateUrlPart)) {
      const normalized = normalizeUrl(candidateUrlPart);
      if (normalized) {
        return buildIntent(normalized, candidateGoalPart || null);
      }
    }
  }

  // 2. Check for URL followed by whitespace and quoted goal:
  const quotedGoalMatch = trimmed.match(/^(\S+)\s+(["'“].+["'”])$/);
  if (quotedGoalMatch) {
    const candidateUrlPart = quotedGoalMatch[1].trim();
    const candidateGoalPart = stripQuotes(quotedGoalMatch[2].trim());

    if (looksLikeUrl(candidateUrlPart)) {
      const normalized = normalizeUrl(candidateUrlPart);
      if (normalized) {
        return buildIntent(normalized, candidateGoalPart || null);
      }
    }
  }

  // 3. Check for URL/domain followed by whitespace and unquoted goal text:
  // e.g. "https://example.com test login flow"
  const spaceGoalMatch = trimmed.match(/^(\S+)\s+([a-zA-Z0-9].*)$/);
  if (spaceGoalMatch) {
    const candidateUrlPart = spaceGoalMatch[1].trim();
    const candidateGoalPart = stripQuotes(spaceGoalMatch[2].trim());

    if (looksLikeUrl(candidateUrlPart)) {
      const normalized = normalizeUrl(candidateUrlPart);
      if (normalized) {
        return buildIntent(normalized, candidateGoalPart || null);
      }
    }
  }

  // 4. Check if the entire string is a URL (or domain without protocol)
  if (looksLikeUrl(trimmed)) {
    const normalized = normalizeUrl(trimmed);
    if (normalized) {
      return buildIntent(normalized, null);
    }
  }

  // 5. Fallback: Natural language goal without URL
  return buildIntent(null, stripQuotes(trimmed));
}
