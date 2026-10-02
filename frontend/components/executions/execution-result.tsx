"use client";

import type { ExecutionDetail } from "@/lib/types";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ExecutionResultProps {
  execution: ExecutionDetail;
  onRetry?: () => void;
  isRetrying?: boolean;
  className?: string;
}

function calculateDuration(startedAt?: string | null, completedAt?: string | null): string | null {
  if (!startedAt || !completedAt) return null;
  try {
    const start = new Date(startedAt).getTime();
    const end = new Date(completedAt).getTime();
    const diff = end - start;
    if (diff < 0) return null;
    return `${(diff / 1000).toFixed(1)}s`;
  } catch {
    return null;
  }
}

export function ExecutionResult({
  execution,
  onRetry,
  isRetrying = false,
  className,
}: ExecutionResultProps) {
  const duration = calculateDuration(execution.startedAt, execution.completedAt);

  if (execution.status === "completed") {
    return (
      <section
        aria-label="Execution result"
        className={cn(
          "rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-5 shadow-xs",
          className
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
              <MaterialIcon name="check_circle" size={20} />
            </div>
            <div>
              <h3 className="text-body font-semibold text-emerald-700 dark:text-emerald-400">
                Mission completed
              </h3>
              <p className="text-body-sm text-foreground/80 mt-0.5 leading-relaxed">
                Kova accomplished the mission and verified application state.
              </p>
            </div>
          </div>

          {duration && (
            <span className="text-caption font-mono text-muted-foreground bg-background/60 px-2.5 py-1 rounded-md border border-border/60 shrink-0">
              {duration}
            </span>
          )}
        </div>
      </section>
    );
  }

  if (execution.status === "failed") {
    return (
      <section
        aria-label="Execution result"
        className={cn(
          "rounded-2xl border border-destructive/20 bg-destructive/5 p-5 shadow-xs space-y-4",
          className
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
              <MaterialIcon name="error" size={20} />
            </div>
            <div>
              <h3 className="text-body font-semibold text-destructive">
                Execution failed
              </h3>
              <p className="text-body-sm text-foreground/80 mt-0.5 leading-relaxed">
                {execution.error || "Kova couldn't complete this mission."}
              </p>
            </div>
          </div>

          {duration && (
            <span className="text-caption font-mono text-muted-foreground bg-background/60 px-2.5 py-1 rounded-md border border-border/60 shrink-0">
              {duration}
            </span>
          )}
        </div>

        {onRetry && (
          <div className="pt-1 flex justify-end">
            <Button
              variant="outline"
              size="sm"
              onClick={onRetry}
              disabled={isRetrying}
              className="gap-1.5 rounded-xl border-border/80 text-foreground hover:bg-secondary/40"
            >
              {isRetrying ? (
                <MaterialIcon name="progress_activity" size={14} className="animate-spin" />
              ) : (
                <MaterialIcon name="replay" size={14} />
              )}
              <span>Run again</span>
            </Button>
          </div>
        )}
      </section>
    );
  }

  if (execution.status === "timeout") {
    return (
      <section
        aria-label="Execution result"
        className={cn(
          "rounded-2xl border border-destructive/20 bg-destructive/5 p-5 shadow-xs space-y-4",
          className
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
              <MaterialIcon name="timer_off" size={20} />
            </div>
            <div>
              <h3 className="text-body font-semibold text-destructive">
                Execution timed out
              </h3>
              <p className="text-body-sm text-foreground/80 mt-0.5 leading-relaxed">
                Kova couldn&apos;t complete the mission within the allowed time.
              </p>
            </div>
          </div>

          {duration && (
            <span className="text-caption font-mono text-muted-foreground bg-background/60 px-2.5 py-1 rounded-md border border-border/60 shrink-0">
              {duration}
            </span>
          )}
        </div>

        {onRetry && (
          <div className="pt-1 flex justify-end">
            <Button
              variant="outline"
              size="sm"
              onClick={onRetry}
              disabled={isRetrying}
              className="gap-1.5 rounded-xl border-border/80 text-foreground hover:bg-secondary/40"
            >
              {isRetrying ? (
                <MaterialIcon name="progress_activity" size={14} className="animate-spin" />
              ) : (
                <MaterialIcon name="replay" size={14} />
              )}
              <span>Run again</span>
            </Button>
          </div>
        )}
      </section>
    );
  }

  if (execution.status === "cancelled") {
    return (
      <section
        aria-label="Execution result"
        className={cn(
          "rounded-2xl border border-border/80 bg-secondary/20 p-5 shadow-xs space-y-4",
          className
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-muted-foreground">
              <MaterialIcon name="cancel" size={20} />
            </div>
            <div>
              <h3 className="text-body font-semibold text-foreground">
                Execution cancelled
              </h3>
              <p className="text-body-sm text-muted-foreground mt-0.5 leading-relaxed">
                Kova stopped this execution.
              </p>
            </div>
          </div>

          {duration && (
            <span className="text-caption font-mono text-muted-foreground bg-background/60 px-2.5 py-1 rounded-md border border-border/60 shrink-0">
              {duration}
            </span>
          )}
        </div>

        {onRetry && (
          <div className="pt-1 flex justify-end">
            <Button
              variant="outline"
              size="sm"
              onClick={onRetry}
              disabled={isRetrying}
              className="gap-1.5 rounded-xl border-border/80 text-foreground hover:bg-secondary/40"
            >
              {isRetrying ? (
                <MaterialIcon name="progress_activity" size={14} className="animate-spin" />
              ) : (
                <MaterialIcon name="replay" size={14} />
              )}
              <span>Run again</span>
            </Button>
          </div>
        )}
      </section>
    );
  }

  return null;
}
