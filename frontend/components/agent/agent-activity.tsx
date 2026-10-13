"use client";

import { MaterialIcon } from "@/components/shared/material-icon";
import type { AgentActivityItem } from "@/lib/types";
import { cn } from "@/lib/utils";

interface AgentActivityProps {
  activities: AgentActivityItem[];
  title?: string;
  className?: string;
}

/**
 * Defensive guardrail to ensure no raw model chain-of-thought, private reasoning,
 * or raw technical logs leak to the user interface.
 */
function sanitizeActivityMessage(message: string): string {
  if (/^(i think|my reasoning|reasoning:|chain of thought)/i.test(message)) {
    return "Analyzing interface structure";
  }
  if (/^(post|get|put|delete|patch)\s+\//i.test(message)) {
    return "Interacting with service";
  }
  if (/\b\d+\s+nodes discovered\b/i.test(message)) {
    return "Scanning page structure";
  }
  return message;
}

export function AgentActivity({
  activities,
  title = "Activity",
  className,
}: AgentActivityProps) {
  if (activities.length === 0) return null;

  // Identify the single active activity (last active item wins)
  const lastActiveIndex = activities.reduce((lastIdx, act, idx) => {
    return act.status === "active" ? idx : lastIdx;
  }, -1);

  const completedCount = activities.filter(
    (a, idx) => a.status === "completed" || (a.status === "active" && idx !== lastActiveIndex)
  ).length;

  return (
    <div className={cn("flex flex-col space-y-2", className)}>
      {title && (
        <div className="flex items-center justify-between px-1 mb-1">
          <span className="text-caption font-medium uppercase tracking-wider text-muted-foreground/70">
            {title}
          </span>
          <span className="text-[11px] font-mono text-muted-foreground/50">
            {completedCount}/{activities.length}
          </span>
        </div>
      )}

      <div className="space-y-1.5" role="log" aria-live="polite">
        {activities.map((item, index) => {
          const displayMessage = sanitizeActivityMessage(item.message);
          const isCurrentActive = item.status === "active" && index === lastActiveIndex;
          const isCompleted = item.status === "completed" || (item.status === "active" && index !== lastActiveIndex);

          return (
            <div
              key={item.id}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 transition-all duration-300",
                isCurrentActive && "bg-primary/5 border border-primary/20 shadow-xs",
                isCompleted && "bg-transparent opacity-90",
                item.status === "failed" && "bg-destructive/5 border border-destructive/20",
                item.status === "pending" && "opacity-50"
              )}
            >
              <div className="shrink-0 flex items-center justify-center w-4 h-4">
                {isCompleted && (
                  <MaterialIcon
                    name="check_circle"
                    size={16}
                    className="text-emerald-500 font-medium"
                  />
                )}
                {isCurrentActive && (
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-primary" />
                  </span>
                )}
                {item.status === "pending" && (
                  <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
                )}
                {item.status === "failed" && (
                  <MaterialIcon
                    name="cancel"
                    size={16}
                    className="text-destructive font-medium"
                  />
                )}
              </div>

              <span
                className={cn(
                  "text-body-sm transition-colors",
                  isCompleted && "text-muted-foreground",
                  isCurrentActive && "font-medium text-foreground",
                  item.status === "pending" && "text-muted-foreground/60",
                  item.status === "failed" && "text-destructive"
                )}
              >
                {displayMessage}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
