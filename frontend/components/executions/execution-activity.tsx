"use client";

import { useEffect, useRef } from "react";
import type { ActivityItem } from "@/lib/types";
import { MaterialIcon } from "@/components/shared/material-icon";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

interface ExecutionActivityProps {
  activities: ActivityItem[];
  className?: string;
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
}: ExecutionActivityProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activities.length]);

  if (activities.length === 0) {
    return (
      <div
        className={cn(
          "rounded-2xl border border-border/80 bg-card/60 p-6 text-center flex items-center justify-center h-[480px]",
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
        "rounded-2xl border border-border/80 bg-card/60 p-5 shadow-xs flex flex-col h-[480px]",
        className
      )}
    >
      <div className="flex items-center justify-between pb-3 border-b border-border/40 shrink-0">
        <h2 className="text-body-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Activity stream
        </h2>
        <span className="inline-flex items-center rounded-full bg-secondary/70 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
          {activities.length} {activities.length === 1 ? "event" : "events"}
        </span>
      </div>

      <div className="flex-1 min-h-0 overflow-hidden mt-1">
        <ScrollArea className="h-full w-full pr-3">
          <div
            aria-live="polite"
            className="relative space-y-2 py-2 before:absolute before:left-3 before:top-2 before:bottom-2 before:w-[1px] before:bg-border/60"
          >
        {activities.map((item) => {
          const formattedTime = formatTime(item.timestamp);

          return (
            <div
              key={item.id}
              className={cn(
                "group relative flex items-start gap-3 rounded-xl px-2.5 py-1.5 transition-colors",
                item.status === "active" && "bg-primary/5",
                item.status === "failed" && "bg-destructive/5"
              )}
            >
              <div className="relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-card">
                {item.status === "completed" && (
                  <MaterialIcon
                    name={item.icon ?? "check_circle"}
                    size={16}
                    className="text-emerald-600 dark:text-emerald-400"
                  />
                )}
                {item.status === "active" && (
                  <MaterialIcon
                    name="progress_activity"
                    size={15}
                    className="animate-spin text-primary"
                  />
                )}
                {item.status === "pending" && (
                  <MaterialIcon
                    name={item.icon ?? "radio_button_unchecked"}
                    size={15}
                    className="text-muted-foreground/40"
                  />
                )}
                {item.status === "failed" && (
                  <MaterialIcon
                    name="error"
                    size={16}
                    className="text-destructive"
                  />
                )}
              </div>

              <div className="min-w-0 flex-1 pt-0.5 flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-1">
                <span
                  className={cn(
                    "text-body-sm leading-snug",
                    item.status === "completed" && "text-foreground/90",
                    item.status === "active" && "font-medium text-primary",
                    item.status === "pending" && "text-muted-foreground/80",
                    item.status === "failed" && "font-medium text-destructive"
                  )}
                >
                  {item.label}
                </span>

                {formattedTime && (
                  <span className="text-caption font-mono text-muted-foreground/80 shrink-0 text-right">
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
