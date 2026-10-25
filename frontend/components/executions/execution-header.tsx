"use client";

import type { ExecutionDetail } from "@/lib/types";
import { getExecutionStatusConfig } from "@/lib/utils/execution-status";
import { isActiveStatus } from "@/lib/executions/status";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { MaterialIcon } from "@/components/shared/material-icon";
import { ModeBadge } from "@/components/shared/mode-badge";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import type { StreamConnectionStatus } from "@/lib/realtime/types";

interface ExecutionHeaderProps {
  execution: ExecutionDetail;
  connectionStatus?: StreamConnectionStatus;
  onStopClick?: () => void;
  onRetryClick?: () => void;
  isRetrying?: boolean;
  onShareClick?: () => void;
  onExportPdfClick?: () => void;
  isSharing?: boolean;
  shareSuccess?: string | null;
}

function formatHostname(url: string): string {
  try {
    return new URL(url.startsWith("http") ? url : `https://${url}`).hostname;
  } catch {
    return url;
  }
}

export function ExecutionHeader({
  execution,
  connectionStatus,
  onStopClick,
  onRetryClick,
  isRetrying = false,
  onShareClick,
  onExportPdfClick,
  isSharing = false,
  shareSuccess = null,
}: ExecutionHeaderProps) {
  const statusConfig = getExecutionStatusConfig(execution.status);
  const isActive = isActiveStatus(execution.status);
  const backHref = execution.missionId
    ? `/flows/${execution.missionId}`
    : "/executions";

  return (
    <div className="mb-6 space-y-3">
      {/* Breadcrumbs */}
      <Breadcrumbs parentHref={backHref} parentLabel="Flow" currentLabel="Proof Run" />

      {/* Title & Actions Bar */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-display sm:text-[2.25rem] font-bold text-foreground mb-1.5 tracking-tight truncate">
            {execution.missionName}
          </h1>

          <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-body-sm text-muted-foreground">
            <span className="font-medium text-foreground">
              {execution.projectName}
            </span>
            {execution.projectUrl && (
              <>
                <span aria-hidden="true">·</span>
                <span className="font-mono text-caption">
                  {formatHostname(execution.projectUrl)}
                </span>
              </>
            )}
            <span aria-hidden="true">·</span>

            {/* Execution Status Badge */}
            <StatusBadge config={statusConfig} className="px-2 py-0.5 rounded-md" />

            {/* Validation Mode Badge */}
            <ModeBadge mode={execution.mode} />

            {/* Subtle Restrained Realtime Stream Indicator */}
            {isActive && connectionStatus === "connected" && (
              <span
                className="inline-flex items-center gap-1.5 text-caption font-medium px-2 py-0.5 rounded-md bg-primary/8 text-primary border border-primary/20"
                aria-label="Realtime stream connected"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
                <span>Live updates</span>
              </span>
            )}

            {isActive && connectionStatus === "reconnecting" && (
              <span
                className="inline-flex items-center gap-1.5 text-caption font-medium px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20"
                aria-label="Realtime stream reconnecting"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
                <span>Reconnecting…</span>
              </span>
            )}

            {isActive && connectionStatus === "unavailable" && (
              <span
                className="inline-flex items-center gap-1.5 text-caption text-muted-foreground px-2 py-0.5 rounded-md bg-secondary/50 border border-border/50"
                title="SSE stream not available from server. Showing latest state."
              >
                <MaterialIcon name="info" size={12} className="text-muted-foreground/80" />
                <span>Live updates unavailable. Showing latest state.</span>
              </span>
            )}
          </div>
        </div>

        {/* Header Action Buttons */}
        <div className="flex items-center gap-2 shrink-0">
          {!isActive && onShareClick && (
            <Button
              variant="outline"
              size="sm"
              onClick={onShareClick}
              disabled={isSharing}
              className="gap-1.5 rounded-xl border-border/80 text-foreground hover:bg-secondary/40"
              title="Copy signed, shareable audit report link"
            >
              <MaterialIcon
                name={shareSuccess ? "check" : "share"}
                size={16}
                className={shareSuccess ? "text-emerald-500" : "text-muted-foreground"}
              />
              <span>{shareSuccess ? "Copied!" : "Share"}</span>
            </Button>
          )}

          {!isActive && onExportPdfClick && (
            <Button
              variant="outline"
              size="sm"
              onClick={onExportPdfClick}
              className="gap-1.5 rounded-xl border-border/80 text-foreground hover:bg-secondary/40"
              title="Open print-ready report in new window"
            >
              <MaterialIcon name="picture_as_pdf" size={16} className="text-muted-foreground" />
              <span>Export PDF</span>
            </Button>
          )}

          {isActive && onStopClick && (
            <Button
              variant="outline"
              size="sm"
              onClick={onStopClick}
              className="gap-1.5 rounded-xl border-border/80 text-foreground hover:bg-secondary/40"
            >
              <MaterialIcon name="stop" size={16} className="text-muted-foreground" />
              <span>Stop</span>
            </Button>
          )}

          {!isActive && onRetryClick && (
            <Button
              size="sm"
              onClick={onRetryClick}
              disabled={isRetrying}
              className="gap-1.5 rounded-xl font-medium shadow-sm"
            >
              {isRetrying ? (
                <MaterialIcon name="progress_activity" size={16} className="animate-spin" />
              ) : (
                <MaterialIcon name="replay" size={16} />
              )}
              <span>Run again</span>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

