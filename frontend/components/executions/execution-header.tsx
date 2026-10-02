"use client";

import Link from "next/link";
import type { ExecutionDetail } from "@/lib/types";
import { getExecutionStatusConfig } from "@/lib/utils/execution-status";
import { isActiveStatus } from "@/lib/executions/status";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { StreamConnectionStatus } from "@/lib/realtime/types";

interface ExecutionHeaderProps {
  execution: ExecutionDetail;
  connectionStatus?: StreamConnectionStatus;
  onStopClick?: () => void;
  onRetryClick?: () => void;
  isRetrying?: boolean;
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
}: ExecutionHeaderProps) {
  const statusConfig = getExecutionStatusConfig(execution.status);
  const isActive = isActiveStatus(execution.status);
  const backHref = execution.missionId
    ? `/flows/${execution.missionId}`
    : "/executions";

  return (
    <div className="mb-6 space-y-3">
      {/* Breadcrumbs */}
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-body-sm text-muted-foreground">
        <Link
          href={backHref}
          className="inline-flex items-center gap-1 hover:text-foreground transition-colors"
        >
          <MaterialIcon name="arrow_back" size={16} />
          <span>Mission</span>
        </Link>
        <span className="text-border">/</span>
        <span className="text-foreground font-medium truncate max-w-[200px] sm:max-w-xs">
          Execution
        </span>
      </nav>

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
            <span
              className={cn(
                "inline-flex items-center gap-1.5 text-caption font-medium px-2 py-0.5 rounded-md",
                statusConfig.badgeClass
              )}
            >
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  statusConfig.dotClass,
                  statusConfig.isAnimated && "animate-pulse"
                )}
              />
              <span>{statusConfig.label}</span>
            </span>

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
