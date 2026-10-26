import type { StatusStyleConfig } from "@/lib/utils/execution-status";

/**
 * Backend run statuses. Source: ValidationStatus enum
 * (backend/app/modules/validation/models.py) plus "CANCELLED"
 * set directly by POST /runs/{id}/cancel.
 */
export const RUN_STATUSES = [
  "RUNNING",
  "PAUSED",
  "PASSED",
  "FAILED",
  "BLOCKED",
  "UNVERIFIED",
  "ERROR",
  "CANCELLED",
] as const;

export type RunStatus = (typeof RUN_STATUSES)[number];

const VALID_RUN_STATUSES = new Set<string>(RUN_STATUSES);

export function normalizeRunStatus(
  rawStatus: string | null | undefined
): RunStatus {
  if (!rawStatus) return "RUNNING";
  const clean = rawStatus.trim().toUpperCase().replace(/[-\s]/g, "_");
  if (VALID_RUN_STATUSES.has(clean)) return clean as RunStatus;
  return "RUNNING";
}

const TERMINAL_RUN_STATUSES = new Set<RunStatus>([
  "PASSED",
  "FAILED",
  "BLOCKED",
  "UNVERIFIED",
  "ERROR",
  "CANCELLED",
]);

export function isTerminalRunStatus(status: RunStatus | string): boolean {
  return TERMINAL_RUN_STATUSES.has(normalizeRunStatus(status));
}

export function isActiveRunStatus(status: RunStatus | string): boolean {
  return !isTerminalRunStatus(status);
}

const RUN_STATUS_CONFIGS: Record<RunStatus, StatusStyleConfig> = {
  RUNNING: {
    label: "RUNNING",
    badgeClass: "bg-blue-500/10 text-blue-600 border-blue-500/20",
    dotClass: "bg-blue-500",
    iconName: "sync",
    isAnimated: true,
  },
  PAUSED: {
    label: "PAUSED",
    badgeClass: "bg-amber-500/10 text-amber-600 border-amber-500/20",
    dotClass: "bg-amber-500",
    iconName: "pause_circle",
    isAnimated: false,
  },
  PASSED: {
    label: "PASSED",
    badgeClass: "bg-emerald-500/10 text-emerald-600 border-emerald-500/20",
    dotClass: "bg-emerald-500",
    iconName: "check_circle",
    isAnimated: false,
  },
  FAILED: {
    label: "FAILED",
    badgeClass: "bg-destructive/10 text-destructive border-destructive/20",
    dotClass: "bg-destructive",
    iconName: "error",
    isAnimated: false,
  },
  CANCELLED: {
    label: "CANCELLED",
    badgeClass: "bg-muted text-muted-foreground border-border",
    dotClass: "bg-muted-foreground",
    iconName: "cancel",
    isAnimated: false,
  },
  BLOCKED: {
    label: "BLOCKED",
    badgeClass: "bg-amber-500/10 text-amber-600 border-amber-500/20",
    dotClass: "bg-amber-500",
    iconName: "block",
    isAnimated: false,
  },
  UNVERIFIED: {
    label: "UNVERIFIED",
    badgeClass: "bg-amber-500/10 text-amber-600 border-amber-500/20",
    dotClass: "bg-amber-500",
    iconName: "help",
    isAnimated: false,
  },
  ERROR: {
    label: "ERROR",
    badgeClass: "bg-destructive/10 text-destructive border-destructive/20",
    dotClass: "bg-destructive",
    iconName: "error_outline",
    isAnimated: false,
  },
};

export function getRunStatusConfig(status: RunStatus | string): StatusStyleConfig {
  return RUN_STATUS_CONFIGS[normalizeRunStatus(status)];
}
