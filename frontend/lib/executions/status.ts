import type { ExecutionStatus } from "@/lib/types";
import {
  humanStatusLabels,
  humanStatusShortLabels,
  getExecutionStatusConfig,
  type StatusStyleConfig,
} from "@/lib/utils/execution-status";

export {
  humanStatusLabels,
  humanStatusShortLabels,
  getExecutionStatusConfig,
  type StatusStyleConfig,
};

/**
 * Backend ExecutionStatus enum values matching backend/app/modules/executions/models.py
 */
export const BACKEND_EXECUTION_STATUSES = [
  "CREATED",
  "QUEUED",
  "INITIALIZING",
  "BROWSER_READY",
  "RUNNING",
  "WAITING",
  "PAUSED",
  "HUMAN_CONTROLLED",
  "RESUMING",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
  "TIMEOUT",
  "BLOCKED",
  "UNVERIFIED",
] as const;

export type BackendExecutionStatus = (typeof BACKEND_EXECUTION_STATUSES)[number];

const VALID_FRONTEND_STATUSES = new Set<ExecutionStatus>([
  "created",
  "queued",
  "initializing",
  "browser_ready",
  "running",
  "waiting",
  "paused",
  "human_controlled",
  "resuming",
  "completed",
  "failed",
  "cancelled",
  "timeout",
  "blocked",
  "unverified",
]);

/**
 * Normalizes any backend or raw status string (e.g. "RUNNING", "Running", "browser_ready")
 * into the canonical frontend ExecutionStatus.
 */
export function normalizeExecutionStatus(
  rawStatus: string | null | undefined
): ExecutionStatus {
  if (!rawStatus) return "created";

  const clean = rawStatus.trim().toLowerCase().replace(/[-\s]/g, "_");

  if (VALID_FRONTEND_STATUSES.has(clean as ExecutionStatus)) {
    return clean as ExecutionStatus;
  }

  return "created";
}

/**
 * Checks whether an execution status is terminal (execution has concluded).
 */
export function isTerminalStatus(status: ExecutionStatus | string): boolean {
  const normalized = normalizeExecutionStatus(status);
  return (
    normalized === "completed" ||
    normalized === "failed" ||
    normalized === "cancelled" ||
    normalized === "timeout" ||
    normalized === "blocked" ||
    normalized === "unverified"
  );
}

/**
 * Checks whether an execution status represents active, in-progress or queued work.
 */
export function isActiveStatus(status: ExecutionStatus | string): boolean {
  return !isTerminalStatus(status);
}

/**
 * Returns conversational, user-facing editorial label for an execution status.
 */
export function getExecutionStatusLabel(
  status: ExecutionStatus | string
): string {
  const normalized = normalizeExecutionStatus(status);
  return humanStatusLabels[normalized] ?? "Preparing execution";
}

/**
 * Returns compact label for compact tables and badges.
 */
export function getExecutionStatusShortLabel(
  status: ExecutionStatus | string
): string {
  const normalized = normalizeExecutionStatus(status);
  return humanStatusShortLabels[normalized] ?? "Preparing";
}
