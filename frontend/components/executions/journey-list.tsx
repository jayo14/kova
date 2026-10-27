"use client";

import { useState } from "react";
import type { RunExecutionItem } from "@/lib/api/runs";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";
import { isActiveStatus, normalizeExecutionStatus } from "@/lib/executions/status";

const WORKING_STATUSES = ["running", "initializing", "browser_ready", "resuming"];

interface JourneyListProps {
  executions: RunExecutionItem[];
  selectedExecutionId: string | null;
  onSelect: (executionId: string) => void;
}

export function JourneyList({
  executions,
  selectedExecutionId,
  onSelect,
}: JourneyListProps) {
  const [open, setOpen] = useState(true);

  return (
    <section className="rounded-[20px] border border-border/70 bg-card shadow-[0_1px_2px_rgba(42,23,13,0.04)]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
      >
        <h2 className="text-sm font-semibold tracking-tight text-foreground">
          Selected Missions <span className="text-muted-foreground">({executions.length})</span>
        </h2>
        <MaterialIcon
          name="expand_more"
          size={18}
          className={cn(
            "text-muted-foreground transition-transform duration-200",
            !open && "-rotate-90"
          )}
        />
      </button>

      {open && (
        <div className="px-4 pb-4">
          {executions.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border/70 p-6 text-center">
              <p className="text-xs text-muted-foreground">No missions in this run.</p>
            </div>
          ) : (
            <div className="max-h-[520px] space-y-1.5 overflow-y-auto pr-0.5">
              {executions.map((item, index) => {
                const isSelected = item.id === selectedExecutionId;
                const normStatus = normalizeExecutionStatus(item.status);
                const isItemActive =
                  isActiveStatus(normStatus) &&
                  normStatus !== "created" &&
                  normStatus !== "queued";
                const isItemWorking = WORKING_STATUSES.includes(normStatus);
                const isFailed = normStatus === "failed" || normStatus === "error";
                const errorText = item.errorMessage || null;

                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onSelect(item.id)}
                    aria-pressed={isSelected}
                    className={cn(
                      "w-full min-w-0 rounded-xl border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      isSelected
                        ? "border-[color:var(--line)] bg-[var(--sand)]/55"
                        : "border-transparent hover:bg-secondary/50"
                    )}
                  >
                    <div className="flex items-start gap-3">
                      <span
                        className={cn(
                          "mt-px flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ring-1",
                          isFailed
                            ? "bg-destructive/10 text-destructive ring-destructive/20"
                            : isSelected
                              ? "bg-card text-foreground ring-border/70"
                              : "bg-secondary text-muted-foreground ring-border/60"
                        )}
                      >
                        <MaterialIcon
                          name={isFailed ? "close" : isItemWorking ? "sync" : "task_alt"}
                          size={15}
                          className={cn(isItemWorking && "animate-spin")}
                        />
                      </span>

                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-2">
                          <span
                            title={item.missionName || "User Journey"}
                            className="line-clamp-2 text-xs font-semibold leading-snug text-foreground"
                          >
                            {item.missionName || "User Journey"}
                          </span>
                          <span
                            className={cn(
                              "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide",
                              normStatus === "completed"
                                ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                                : isFailed
                                  ? "bg-destructive/10 text-destructive"
                                  : isItemActive
                                    ? "bg-blue-500/10 text-blue-700 dark:text-blue-400"
                                    : "bg-secondary text-muted-foreground"
                            )}
                          >
                            {isItemWorking && (
                              <MaterialIcon name="sync" className="h-3 w-3 animate-spin" />
                            )}
                            {normStatus.toUpperCase()}
                          </span>
                        </div>

                        <div className="mt-1 flex items-center justify-between gap-3 text-[10px] text-muted-foreground">
                          <span className="truncate font-mono">
                            ID: {item.id.slice(0, 8)}
                          </span>
                          <span className="shrink-0 font-mono tabular-nums">
                            {item.durationMs
                              ? `${(item.durationMs / 1000).toFixed(1)}s`
                              : `Mission ${index + 1}`}
                          </span>
                        </div>

                        {errorText && (
                          <p
                            title={errorText}
                            className="mt-1.5 line-clamp-1 break-words text-[10px] text-destructive"
                          >
                            {errorText}
                          </p>
                        )}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
