"use client";

import { useEffect, useRef } from "react";
import type { ActivityItem } from "@/lib/types";
import { MaterialIcon } from "@/components/shared/material-icon";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

interface ExecutionActivityProps {
  activities: ActivityItem[];
  className?: string;
  variant?: "default" | "rail";
}

function formatTime(iso?: string): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return "";
  }
}

export function ExecutionActivity({
  activities,
  className,
  variant = "default",
}: ExecutionActivityProps) {
  const isRail = variant === "rail";
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activities.length]);

  if (activities.length === 0) {
    return (
      <div
        className={cn(
          "flex h-[480px] items-center justify-center rounded-[20px] border border-border/70 bg-card p-6 text-center shadow-[0_1px_2px_rgba(42,23,13,0.04)]",
          className
        )}
      >
        <p className="text-body-sm text-muted-foreground">
          Waiting for events... Kova is starting work.
        </p>
      </div>
    );
  }

  return (
    <section
      aria-label="Activity timeline"
      className={cn(
        "flex h-[480px] flex-col rounded-[20px] border border-border/70 bg-card shadow-[0_1px_2px_rgba(42,23,13,0.04)]",
        isRail ? "p-4" : "p-5",
        className
      )}
    >
      <div className="flex shrink-0 items-center justify-between border-b border-border/60 px-1 pb-3">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">
          Activity stream
        </h2>
        <span className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
          {activities.length} {activities.length === 1 ? "event" : "events"}
        </span>
      </div>

      <div className="flex-1 min-h-0 overflow-hidden mt-1">
        <ScrollArea className={cn("h-full w-full", isRail ? "pr-2" : "pr-3")}>
          <div
            aria-live="polite"
            className={cn(
              "relative py-2 before:absolute before:bottom-3 before:top-3 before:w-px before:bg-border/70",
              isRail ? "space-y-1 before:left-[19px]" : "space-y-2 before:left-[22px]"
            )}
          >
        {activities.map((item) => {
          const formattedTime = formatTime(item.timestamp);

          return (
            <div
              key={item.id}
              className={cn(
                "group relative flex items-start gap-2.5 rounded-xl px-1 py-1.5 transition-colors",
                item.status === "active" && "bg-primary/5",
                item.status === "failed" && "bg-destructive/5"
              )}
            >
              <div
                className={cn(
                  "relative z-10 flex shrink-0 items-center justify-center rounded-lg bg-card ring-1 ring-border/60",
                  isRail ? "h-6 w-6" : "h-7 w-7"
                )}
              >
                {item.status === "completed" && (
                  <MaterialIcon
                    name={item.icon ?? "check_circle"}
                    size={isRail ? 14 : 16}
                    className="text-emerald-600 dark:text-emerald-400"
                  />
                )}
                {item.status === "active" && (
                  <MaterialIcon
                    name="progress_activity"
                    size={isRail ? 14 : 15}
                    className="animate-spin text-primary"
                  />
                )}
                {item.status === "pending" && (
                  <MaterialIcon
                    name={item.icon ?? "radio_button_unchecked"}
                    size={isRail ? 13 : 15}
                    className="text-muted-foreground/40"
                  />
                )}
                {item.status === "failed" && (
                  <MaterialIcon
                    name="error"
                    size={isRail ? 14 : 16}
                    className="text-destructive"
                  />
                )}
              </div>

              <div className="flex min-w-0 flex-1 items-start justify-between gap-2 pt-0.5">
                <span
                  className={cn(
                    isRail ? "text-xs leading-snug" : "text-body-sm leading-snug",
                    item.status === "completed" && "text-foreground/90",
                    item.status === "active" && "font-medium text-primary",
                    item.status === "pending" && "text-muted-foreground/80",
                    item.status === "failed" && "font-medium text-destructive"
                  )}
                >
                  {item.label}
                </span>

                {formattedTime && (
                  <span
                    suppressHydrationWarning
                    className="shrink-0 pt-px font-mono text-[10px] tabular-nums text-muted-foreground/80"
                  >
                    {formattedTime}
                  </span>
                )}
              </div>
            </div>
          );
        })}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>
    </div>
  </section>
);
}
