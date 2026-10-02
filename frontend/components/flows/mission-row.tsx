import Link from "next/link";
import type { Mission, MissionExecution } from "@/lib/types";
import { getExecutionStatusConfig } from "@/lib/utils/execution-status";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";

interface MissionRowProps {
  mission: Mission;
  lastExecution?: MissionExecution | null;
  executionCount?: number;
}

function relativeTime(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days === 1) return "yesterday";
    if (days < 30) return `${days}d ago`;
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

export function MissionRow({
  mission,
  lastExecution,
  executionCount,
}: MissionRowProps) {
  const statusConfig = lastExecution
    ? getExecutionStatusConfig(lastExecution.status)
    : null;

  return (
    <Link
      href={`/flows/${mission.id}`}
      className="group flex items-center justify-between gap-4 rounded-xl border border-border/80 bg-card px-4 py-3.5 transition-all duration-200 hover:border-muted-foreground/30 hover:bg-secondary/20 shadow-xs"
    >
      <div className="min-w-0 flex-1">
        <h3 className="text-body font-semibold text-foreground truncate group-hover:text-primary transition-colors">
          {mission.name}
        </h3>
        <div className="flex items-center gap-1.5 mt-0.5 text-body-sm text-muted-foreground">
          <span className="truncate">{mission.projectName}</span>
          {mission.persona && (
            <>
              <span aria-hidden="true">·</span>
              <span className="truncate">{mission.persona}</span>
            </>
          )}
          {mission.steps && mission.steps.length > 0 && (
            <>
              <span aria-hidden="true" className="hidden sm:inline">·</span>
              <span className="hidden sm:inline text-caption">
                {mission.steps.length} {mission.steps.length === 1 ? "step" : "steps"}
              </span>
            </>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3 shrink-0">
        {statusConfig && lastExecution ? (
          <span
            className={cn(
              "hidden sm:inline-flex items-center gap-1.5 text-caption font-medium px-2 py-0.5 rounded-md",
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
            <span className="text-muted-foreground/60 font-normal">
              · {relativeTime(lastExecution.createdAt)}
            </span>
          </span>
        ) : executionCount != null && executionCount > 0 ? (
          <span className="text-caption text-muted-foreground hidden sm:inline">
            {executionCount} {executionCount === 1 ? "execution" : "executions"}
          </span>
        ) : null}

        <MaterialIcon
          name="chevron_right"
          size={18}
          className="text-muted-foreground group-hover:text-foreground transition-colors"
        />
      </div>
    </Link>
  );
}
