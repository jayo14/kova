/** Snake ↔ camelCase helpers for API boundary. */

export function toCamel<S extends string>(s: S): CamelCase<S> {
  return s.replace(/_([a-z])/g, (_, c) => c.toUpperCase()) as CamelCase<S>;
}

export function toSnake(s: string): string {
  return s.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);
}

type CamelCase<S extends string> = S extends `${infer Head}_${infer Tail}`
  ? `${Head}${Capitalize<CamelCase<Tail>>}`
  : S;

/** Recursively convert object keys from snake_case to camelCase. */
export function mapKeysToCamel<T>(obj: T): T {
  if (obj === null || obj === undefined || typeof obj !== "object") return obj;
  if (Array.isArray(obj)) return obj.map(mapKeysToCamel) as T;

  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
    const camel = toCamel(k);
    out[camel] =
      v !== null && typeof v === "object" && !Array.isArray(v)
        ? mapKeysToCamel(v)
        : v;
  }
  return out as T;
}

/** Recursively convert object keys from camelCase to snake_case. */
export function mapKeysToSnake<T>(obj: T): T {
  if (obj === null || obj === undefined || typeof obj !== "object") return obj;
  if (Array.isArray(obj)) return obj.map(mapKeysToSnake) as T;

  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
    const snake = toSnake(k);
    out[snake] =
      v !== null && typeof v === "object" && !Array.isArray(v)
        ? mapKeysToSnake(v)
        : v;
  }
  return out as T;
}

/** Strip null/undefined values. Useful before sending to backend. */
export function stripNulls<T extends Record<string, unknown>>(obj: T): Partial<T> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v !== null && v !== undefined) out[k] = v;
  }
  return out as Partial<T>;
}
