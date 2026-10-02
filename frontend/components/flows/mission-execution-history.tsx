import Link from "next/link";
import type { MissionExecution } from "@/lib/types";
import { getExecutionStatusConfig } from "@/lib/utils/execution-status";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";

interface MissionExecutionHistoryProps {
  executions: MissionExecution[];
  missionName: string;
}

function formatExactDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
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

export function MissionExecutionHistory({
  executions,
  missionName,
}: MissionExecutionHistoryProps) {
  if (executions.length === 0) {
    return (
      <section aria-label="Execution history" className="space-y-2">
        <h2 className="text-body-sm font-semibold text-foreground uppercase tracking-wider text-caption">
          Executions
        </h2>
        <p className="text-body-sm text-muted-foreground leading-relaxed">
          No executions yet. Run this mission to see what Kova finds.
        </p>
      </section>
    );
  }

  const [latest, ...previous] = executions;
  const latestStatus = getExecutionStatusConfig(latest.status);

  return (
    <section aria-label="Execution history" className="space-y-5">
      <div>
        <h2 className="text-body-sm font-semibold text-foreground uppercase tracking-wider text-caption mb-3">
          Last execution
        </h2>

        <div className="rounded-2xl border border-border/80 bg-card/60 p-4 shadow-xs">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "inline-flex items-center gap-1.5 text-caption font-medium px-2 py-0.5 rounded-md",
                    latestStatus.badgeClass
                  )}
                >
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full",
                      latestStatus.dotClass,
                      latestStatus.isAnimated && "animate-pulse"
                    )}
                  />
                  <span>{latestStatus.label}</span>
                </span>
                <span className="text-caption text-muted-foreground">
                  {formatExactDate(latest.createdAt)}
                </span>
              </div>
              <p className="text-body-sm font-medium text-foreground mt-1 truncate">
                {missionName}
              </p>
            </div>

            <Link
              href={`/executions/${latest.id}`}
              className="inline-flex items-center gap-1 text-body-xs font-medium text-primary hover:text-primary/80 transition-colors shrink-0"
            >
              <span>View execution</span>
              <MaterialIcon name="arrow_forward" size={14} />
            </Link>
          </div>
        </div>
      </div>

      {previous.length > 0 && (
        <div>
          <h3 className="text-caption font-medium text-muted-foreground mb-2">
            Previous runs
          </h3>
          <div className="divide-y divide-border/60">
            {previous.map((exec) => {
              const statusConfig = getExecutionStatusConfig(exec.status);
              return (
                <Link
                  key={exec.id}
                  href={`/executions/${exec.id}`}
                  className="group flex items-center justify-between py-2 text-body-sm hover:text-primary transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "h-1.5 w-1.5 rounded-full shrink-0",
                        statusConfig.dotClass
                      )}
                      aria-hidden="true"
                    />
                    <span className="text-body-xs font-medium text-foreground group-hover:text-primary transition-colors">
                      {statusConfig.label}
                    </span>
                  </div>
                  <span className="text-caption text-muted-foreground">
                    {relativeTime(exec.createdAt)}
                  </span>
                </Link>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
