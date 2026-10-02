import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
import { getExecutionStatusConfig } from "@/lib/utils/execution-status";
import type { ExecutionDetail, ExecutionStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

interface RecentExecutionsProps {
  executions: ExecutionDetail[];
}

function StatusBadge({ status }: { status: ExecutionStatus }) {
  const config = getExecutionStatusConfig(status);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-caption font-medium select-none",
        config.badgeClass
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          config.dotClass,
          config.isAnimated && "animate-pulse"
        )}
      />
      <span>{config.label}</span>
    </span>
  );
}

export function RecentExecutions({ executions }: RecentExecutionsProps) {
  if (executions.length === 0) return null;

  return (
    <section aria-labelledby="recent-executions-heading">
      <div className="flex items-center justify-between px-1 mb-3">
        <h2
          id="recent-executions-heading"
          className="text-caption font-medium uppercase tracking-wider text-muted-foreground/80"
        >
          Recent executions
        </h2>
        <Link
          href="/executions"
          className="text-caption text-muted-foreground hover:text-foreground transition-colors font-medium"
        >
          View all
        </Link>
      </div>

      <div className="flex flex-col gap-1.5">
        {executions.map((exec) => (
          <Link
            key={exec.id}
            href={`/executions/${exec.id}`}
            className="group flex items-center justify-between rounded-xl border border-border/80 bg-card p-3.5 transition-all duration-200 hover:border-muted-foreground/30 hover:bg-secondary/20 shadow-xs"
          >
            <div className="min-w-0 flex-1 pr-4">
              <p className="text-body-sm font-medium text-foreground truncate group-hover:text-primary transition-colors">
                {exec.missionName || "Unnamed Mission"}
              </p>
              <p className="text-caption text-muted-foreground truncate mt-0.5">
                {exec.projectName || "Default Workspace"}
              </p>
            </div>

            <div className="flex items-center gap-3 shrink-0">
              <StatusBadge status={exec.status} />
              <MaterialIcon
                name="chevron_right"
                size={16}
                className="text-muted-foreground/50 group-hover:text-foreground transition-colors"
              />
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
