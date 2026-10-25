"use client";

import { useEffect, useState, useCallback, useTransition } from "react";
import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
import { normalizeExecutionStatus } from "@/lib/executions/status";
import {
  getRun,
  cancelRun,
  streamRunEvents,
  type RunDetail,
} from "@/lib/api/runs";
import { getExecution, getExecutionEvents } from "@/lib/api/executions";
import { mapExecutionEvents } from "@/lib/executions/event-mapper";
import { ExecutionDetailPage } from "./execution-detail-page";
import { RunHeader } from "./run-header";
import { RunSummaryStats } from "./run-summary-stats";
import type { ExecutionDetail, ActivityItem, ExecutionEvent } from "@/lib/types";

interface RunOverviewProps {
  runId: string;
  initialRun?: RunDetail;
}

export function RunOverview({ runId, initialRun }: RunOverviewProps) {
  const [run, setRun] = useState<RunDetail | null>(initialRun || null);
  const [loading, setLoading] = useState(!initialRun);
  const [error, setError] = useState<string | null>(null);
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(
    initialRun?.executions?.[0]?.id || null
  );

  const [activeExecution, setActiveExecution] = useState<ExecutionDetail | null>(null);
  const [activeEvents, setActiveEvents] = useState<ExecutionEvent[]>([]);
  const [activeActivities, setActiveActivities] = useState<ActivityItem[]>([]);
  const [loadingActive, setLoadingActive] = useState(false);

  const [isCancelling, startCancelTransition] = useTransition();

  // Load run state on mount or runId change
  useEffect(() => {
    let mounted = true;

    async function fetchRunData() {
      try {
        const data = await getRun(runId);
        if (mounted) {
          setRun(data);
          if (!selectedExecutionId && data.executions.length > 0) {
            setSelectedExecutionId(data.executions[0].id);
          }
          setLoading(false);
        }
      } catch (err) {
        if (mounted) {
          setError((err as Error).message || "Failed to load run details");
          setLoading(false);
        }
      }
    }

    fetchRunData();

    // Subscribe to SSE updates
    const unsubscribe = streamRunEvents(runId, {
      onUpdate: (update) => {
        if (!mounted) return;
        setRun((prev) => {
          if (!prev) return prev;
          const updatedExecutions = prev.executions.map((ex) => {
            const match = update.executions.find((u) => u.id === ex.id);
            if (match) {
              return {
                ...ex,
                status: match.status,
                errorCode: match.errorCode ?? ex.errorCode,
                errorMessage: match.errorMessage ?? ex.errorMessage,
              };
            }
            return ex;
          });

          return {
            ...prev,
            status: update.status,
            progress: update.progress,
            summary: update.summary,
            executions: updatedExecutions,
          };
        });
      },
      onDone: () => {
        fetchRunData();
      },
      onError: (streamErr) => {
        console.warn("Run event stream error:", streamErr);
      },
    });

    return () => {
      mounted = false;
      unsubscribe();
    };
  }, [runId]);

  // When selectedExecutionId changes, fetch active execution details
  useEffect(() => {
    if (!selectedExecutionId) return;

    let mounted = true;
    setLoadingActive(true);

    async function loadSelectedExecution() {
      try {
        const [execData, eventsData] = await Promise.all([
          getExecution(selectedExecutionId!),
          getExecutionEvents(selectedExecutionId!).catch(() => []),
        ]);

        if (mounted && execData) {
          setActiveExecution(execData);
          setActiveEvents(eventsData);
          setActiveActivities(mapExecutionEvents(eventsData));
          setLoadingActive(false);
        }
      } catch (err) {
        if (mounted) {
          console.warn("Failed to load selected execution details:", err);
          setLoadingActive(false);
        }
      }
    }

    loadSelectedExecution();

    return () => {
      mounted = false;
    };
  }, [selectedExecutionId]);

  const handleCancelRun = useCallback(() => {
    startCancelTransition(async () => {
      try {
        const updated = await cancelRun(runId);
        setRun(updated);
      } catch (err) {
        console.error("Failed to cancel run:", err);
      }
    });
  }, [runId]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] space-y-4">
        <MaterialIcon name="sync" className="w-8 h-8 animate-spin text-primary" />
        <p className="text-body-sm text-muted-foreground">Loading validation run orchestration...</p>
      </div>
    );
  }

  if (error || !run) {
    return (
      <div className="rounded-lg border border-destructive/20 bg-destructive/10 p-6 text-center space-y-3">
        <MaterialIcon name="error_outline" className="w-8 h-8 text-destructive mx-auto" />
        <h3 className="font-semibold text-foreground">Could not load run</h3>
        <p className="text-body-sm text-muted-foreground">{error || "Run not found"}</p>
        <Link
          href="/executions"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline pt-2"
        >
          <MaterialIcon name="arrow_back" className="w-4 h-4" />
          Back to Runs
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* Top Navigation & Status Bar */}
      <div className="flex flex-col gap-4 bg-card/60 backdrop-blur-sm border border-border/60 rounded-xl p-5 shadow-sm">
        <RunHeader
          runId={run.id}
          status={run.status}
          isCancelling={isCancelling}
          onCancel={handleCancelRun}
        />

        <RunSummaryStats
          summary={run.summary}
          progress={run.progress}
          status={run.status}
        />
      </div>

      {/* Main Two-Column View: Mission Selector + Active Journey Stream */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Mission List */}
        <div className="lg:col-span-4 space-y-3">
          <div className="flex items-center justify-between px-1">
            <h2 className="text-sm font-semibold text-foreground tracking-tight">
              Selected Missions ({run.executions.length})
            </h2>
            <span className="text-xs text-muted-foreground">Click to inspect</span>
          </div>

          <div className="space-y-2 max-h-[700px] overflow-y-auto pr-1">
            {run.executions.map((item, index) => {
              const isSelected = item.id === selectedExecutionId;
              const normStatus = normalizeExecutionStatus(item.status);
              const isItemRunning = [
                "running",
                "initializing",
                "planning",
                "browser_ready",
              ].includes(normStatus);

              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSelectedExecutionId(item.id)}
                  className={`w-full text-left p-3.5 rounded-xl border transition-all text-xs space-y-2 ${
                    isSelected
                      ? "border-primary bg-primary/5 shadow-sm ring-1 ring-primary/20"
                      : "border-border/60 bg-card/60 hover:bg-muted/40 hover:border-border"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="w-5 h-5 rounded-full bg-muted flex items-center justify-center font-mono text-[10px] text-muted-foreground shrink-0">
                        {index + 1}
                      </span>
                      <span className="font-semibold text-foreground line-clamp-1">
                        {item.missionName || "User Journey"}
                      </span>
                    </div>

                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium shrink-0 ${
                        normStatus === "completed"
                          ? "bg-emerald-500/10 text-emerald-600"
                          : normStatus === "failed" || normStatus === "error"
                          ? "bg-destructive/10 text-destructive"
                          : isItemRunning
                          ? "bg-blue-500/10 text-blue-600"
                          : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {isItemRunning && <MaterialIcon name="sync" className="w-3 h-3 animate-spin" />}
                      {normStatus === "completed" && (
                        <MaterialIcon name="check" className="w-3 h-3" />
                      )}
                      {(normStatus === "failed" || normStatus === "error") && (
                        <MaterialIcon name="close" className="w-3 h-3" />
                      )}
                      {normStatus.toUpperCase()}
                    </span>
                  </div>

                  {item.errorMessage && (
                    <p className="text-[11px] text-destructive line-clamp-1 pl-7">
                      {item.errorMessage}
                    </p>
                  )}

                  <div className="flex items-center justify-between text-[10px] text-muted-foreground pl-7">
                    <span>ID: {item.id.slice(0, 8)}</span>
                    {item.durationMs && <span>{(item.durationMs / 1000).toFixed(1)}s</span>}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Right Column: Live Viewport, Scrubber & Detail for Selected Mission */}
        <div className="lg:col-span-8">
          {loadingActive || !activeExecution ? (
            <div className="rounded-xl border border-border/60 bg-card p-12 text-center space-y-3">
              <MaterialIcon name="sync" className="w-7 h-7 animate-spin text-primary mx-auto" />
              <p className="text-body-sm text-muted-foreground">Loading journey execution detail...</p>
            </div>
          ) : (
            <div className="rounded-xl border border-border/60 bg-card overflow-hidden shadow-sm">
              <ExecutionDetailPage
                key={activeExecution.id}
                initialExecution={activeExecution}
                initialActivities={activeActivities}
                initialEvents={activeEvents}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
