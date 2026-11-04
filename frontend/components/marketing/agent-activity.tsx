"use client";

import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";

export type ActivityStatus = "pending" | "running" | "completed";

export interface AgentActivityItem {
  id: string;
  text: string;
  detail?: string;
  status: ActivityStatus;
  count?: number;
  lastSeenTime?: string;
}

interface AgentActivityProps {
  activities: AgentActivityItem[];
  className?: string;
}

export function AgentActivity({ activities, className }: AgentActivityProps) {
  return (
    <div className={cn("space-y-3", className)} role="status" aria-live="polite">
      {activities.map((item) => {
        const isCompleted = item.status === "completed";
        const isRunning = item.status === "running";
        const isPending = item.status === "pending";

        return (
          <div
            key={item.id}
            className={cn(
              "flex items-start gap-3 transition-all duration-300",
              isCompleted && "opacity-100",
              isRunning && "opacity-100 scale-[1.01]",
              isPending && "opacity-35"
            )}
          >
            <div className="mt-0.5 shrink-0">
              {isCompleted ? (
                <MaterialIcon
                  name="check_circle"
                  size={18}
                  className="text-primary transition-transform duration-200"
                  aria-label="Completed"
                />
              ) : isRunning ? (
                <MaterialIcon
                  name="progress_activity"
                  size={18}
                  className="text-primary animate-spin"
                  aria-label="In progress"
                />
              ) : (
                <span
                  className="inline-block h-4 w-4 rounded-full border border-muted-foreground/30 bg-muted/40"
                  aria-label="Pending"
                />
              )}
            </div>

            <div className="flex-1 min-w-0">
              <p
                className={cn(
                  "text-body-sm transition-colors duration-200 leading-snug",
                  isCompleted && "text-foreground font-medium",
                  isRunning && "text-foreground font-medium",
                  isPending && "text-muted-foreground"
                )}
              >
                {item.text}
                {item.count && item.count > 1 ? (
                  <span className="ml-2 text-[10px] font-semibold px-1.5 py-0.2 bg-secondary text-secondary-foreground border border-border/60 rounded">
                    ×{item.count}
                  </span>
                ) : null}
              </p>
              {(item.detail || (item.count && item.count > 1 && item.lastSeenTime)) && (
                <p className="text-caption text-muted-foreground mt-0.5 truncate">
                  {item.detail || `Last seen at ${item.lastSeenTime}`}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
