"use client";

import { useEffect, useState, useCallback, useTransition } from "react";
import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
import {
  getRun,
  cancelRun,
  pauseRun,
  resumeRun,
  getRunControl,
  streamRunEvents,
  type RunDetail,
} from "@/lib/api/runs";
import { getExecution, getExecutionEvents } from "@/lib/api/executions";
import { mapExecutionEvents } from "@/lib/executions/event-mapper";
import { ExecutionDetailPage } from "./execution-detail-page";
import { ExecutionCancelDialog } from "./execution-cancel-dialog";
import { JourneyList } from "./journey-list";
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
  const [cancelDialogOpen, setCancelDialogOpen] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [isPausing, setIsPausing] = useState(false);
  const [isResuming, setIsResuming] = useState(false);

  // Load run state on mount or runId change
  useEffect(() => {
    let mounted = true;

    async function fetchRunData() {
      try {
        const [data, ctrl] = await Promise.all([
          getRun(runId),
          getRunControl(runId).catch(() => null),
        ]);
        if (mounted) {
          setRun(data);
          if (ctrl) {
            setIsPaused(ctrl.state === "paused" || ctrl.state === "human_control");
          }
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

  const handlePauseRun = useCallback(async () => {
    setIsPausing(true);
    try {
      await pauseRun(runId, "User requested pause from Run Overview");
      setIsPaused(true);
    } catch (err) {
      console.error("Failed to pause run:", err);
    } finally {
      setIsPausing(false);
    }
  }, [runId]);

  const handleResumeRun = useCallback(async () => {
    setIsResuming(true);
    try {
      await resumeRun(runId);
      setIsPaused(false);
    } catch (err) {
      console.error("Failed to resume run:", err);
    } finally {
      setIsResuming(false);
    }
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
          onCancel={() => setCancelDialogOpen(true)}
          isPaused={isPaused}
          isPausing={isPausing}
          isResuming={isResuming}
          onPause={handlePauseRun}
          onResume={handleResumeRun}
        />

        <RunSummaryStats
          summary={run.summary}
          progress={run.progress}
          status={run.status}
        />
      </div>

      {/* Main Two-Column View: Mission Selector + Active Journey Stream */}
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        {/* Left Column: Mission List (~290px rail on wide screens) */}
        <div className="lg:w-[290px] lg:shrink-0 min-w-0">
          <JourneyList
            executions={run.executions}
            selectedExecutionId={selectedExecutionId}
            onSelect={setSelectedExecutionId}
          />
        </div>

        {/* Right Column: Live Viewport, Scrubber & Detail for Selected Mission */}
        <div className="flex-1 min-w-0">
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

      <ExecutionCancelDialog
        open={cancelDialogOpen}
        onOpenChange={setCancelDialogOpen}
        title="Stop this run?"
        description={`Kova will stop the remaining missions in run #${run.id.slice(0, 8)}.`}
        onConfirm={() => {
          setCancelDialogOpen(false);
          handleCancelRun();
        }}
        loading={isCancelling}
      />
    </div>
  );
}
