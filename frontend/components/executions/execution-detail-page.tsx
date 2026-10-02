"use client";

import { useState, useCallback, useEffect, useTransition } from "react";
import { useRouter } from "next/navigation";
import type {
  ExecutionDetail as ExecutionDetailType,
  ActivityItem,
} from "@/lib/types";
import type { Evidence } from "@/lib/api/evidence";
import { useExecutionRealtime } from "@/hooks/use-execution-realtime";
import { cancelExecution, createExecution } from "@/lib/api/executions";
import { getExecutionEvidence, refreshEvidenceUrl } from "@/lib/api/evidence";
import { ExecutionHeader } from "./execution-header";
import { ExecutionBrowser } from "./execution-browser";
import { ExecutionActivity } from "./execution-activity";
import { ExecutionResult } from "./execution-result";
import { ExecutionCancelDialog } from "./execution-cancel-dialog";
import { EvidenceList } from "./evidence-list";
import { EvidenceViewer } from "./evidence-viewer";
import { MaterialIcon } from "@/components/shared/material-icon";
import { terminalStatuses } from "@/lib/types";

interface ExecutionDetailPageProps {
  initialExecution: ExecutionDetailType;
  initialActivities?: ActivityItem[];
  initialEvents?: import("@/lib/types").ExecutionEvent[];
}

export function ExecutionDetailPage({
  initialExecution,
  initialActivities = [],
  initialEvents = [],
}: ExecutionDetailPageProps) {
  const router = useRouter();
  const [cancelOpen, setCancelOpen] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isRetrying, startRetryTransition] = useTransition();
  const [actionError, setActionError] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<Evidence | null>(null);

  // Realtime execution stream management via standardized hook
  const {
    execution,
    events,
    activities,
    connectionStatus,
    error: streamError,
    refresh,
    updateExecutionLocally,
  } = useExecutionRealtime({
    executionId: initialExecution.id,
    initialExecution,
    initialActivities,
    initialEvents,
  });

  // Find live screenshot from incoming events, or fallback to loaded evidence
  const liveScreenshot = (() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const p = events[i]?.payload;
      if (p) {
        if (typeof p.screenshot === "string" && p.screenshot) return p.screenshot;
        if (typeof p.screenshot_url === "string" && p.screenshot_url) return p.screenshot_url;
      }
    }
    return evidence.find((e) => e.type === "SCREENSHOT" && e.url)?.url || null;
  })();

  // Find live URL if page was navigated
  const liveUrl = (() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const p = events[i]?.payload;
      if (p && typeof p.url === "string" && p.url) {
        return p.url;
      }
    }
    return execution.projectUrl;
  })();

  const activeActivity =
    activities.find((a) => a.status === "active") ||
    (activities.length > 0 ? activities[activities.length - 1] : null);
  const currentAction = activeActivity?.label || null;

  // Cancel / Stop execution
  const handleCancel = useCallback(async () => {
    setIsCancelling(true);
    setActionError(null);
    try {
      const updated = await cancelExecution(execution.id);
      if (updated) {
        updateExecutionLocally(() => updated);
      }
      setCancelOpen(false);
      await refresh();
      router.refresh();
    } catch {
      setActionError("Failed to stop execution. Please try again.");
    } finally {
      setIsCancelling(false);
    }
  }, [execution.id, updateExecutionLocally, refresh, router]);

  // Run again / Retry -> creates a NEW immutable execution
  const handleRetry = useCallback(() => {
    setActionError(null);
    startRetryTransition(async () => {
      try {
        const newExecution = await createExecution(execution.missionId);
        if (newExecution) {
          router.push(`/executions/${newExecution.id}`);
        } else {
          setActionError("Failed to start new execution.");
        }
      } catch {
        setActionError("Failed to start new execution.");
      }
    });
  }, [execution.missionId, router]);

  const displayError = actionError || streamError;

  // Fetch evidence when execution reaches terminal state
  useEffect(() => {
    if (!terminalStatuses.includes(execution.status)) return;

    let cancelled = false;
    setEvidenceLoading(true);
    setEvidenceError(null);

    getExecutionEvidence(execution.id)
      .then((items) => {
        if (!cancelled) {
          setEvidence(items);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setEvidenceError("Evidence could not be loaded.");
          console.error("Evidence fetch error:", err);
        }
      })
      .finally(() => {
        if (!cancelled) setEvidenceLoading(false);
      });

    return () => { cancelled = true; };
  }, [execution.id, execution.status]);

  return (
    <div className="w-full max-w-5xl mx-auto space-y-6">
      {/* Header with Live Indicator */}
      <ExecutionHeader
        execution={execution}
        connectionStatus={connectionStatus}
        onStopClick={() => setCancelOpen(true)}
        onRetryClick={handleRetry}
        isRetrying={isRetrying}
      />

      {displayError && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-xl bg-destructive/10 px-3.5 py-2.5 text-body-sm text-destructive"
        >
          <MaterialIcon name="error" size={16} />
          <span>{displayError}</span>
        </div>
      )}

      {/* Dominant Browser Workspace Viewport */}
      <ExecutionBrowser
        url={liveUrl}
        status={execution.status}
        errorMessage={execution.error}
        latestScreenshot={liveScreenshot}
        currentAction={currentAction}
        onRetry={handleRetry}
        isRetrying={isRetrying}
        events={events}
        executionId={execution.id}
      />

      {/* 2-Column Section: Activity Stream + Result + Evidence */}
      <div className="grid gap-6 lg:grid-cols-3 pt-2">
        <div className="lg:col-span-2">
          <ExecutionActivity activities={activities} />
        </div>

        <div className="space-y-4">
          <ExecutionResult
            execution={execution}
            onRetry={handleRetry}
            isRetrying={isRetrying}
          />

          {/* Evidence Section */}
          {execution.status === "completed" || execution.status === "failed" ? (
            <div className="rounded-xl border border-border bg-card/50 p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <MaterialIcon name="verified" size={16} className="text-muted-foreground" />
                  <span className="text-body-sm font-semibold text-foreground">Evidence</span>
                </div>
                {evidenceLoading && (
                  <MaterialIcon name="progress_activity" size={14} className="animate-spin text-muted-foreground" />
                )}
              </div>

              {evidenceError ? (
                <div className="text-center py-4">
                  <p className="text-caption text-muted-foreground">{evidenceError}</p>
                </div>
              ) : (
                <EvidenceList
                  evidence={evidence}
                  onEvidenceClick={setSelectedEvidence}
                />
              )}
            </div>
          ) : null}
        </div>
      </div>

      {/* Cancel confirmation dialog */}
      <ExecutionCancelDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        missionName={execution.missionName}
        onConfirm={handleCancel}
        loading={isCancelling}
      />

      {/* Evidence Viewer Dialog */}
      {selectedEvidence && (
        <EvidenceViewer
          evidence={selectedEvidence}
          open={selectedEvidence !== null}
          onClose={() => setSelectedEvidence(null)}
          onRefreshUrl={async (evidenceId) => {
            const freshUrl = await refreshEvidenceUrl(execution.id, evidenceId);
            if (freshUrl) {
              setSelectedEvidence((prev) =>
                prev && prev.id === evidenceId ? { ...prev, url: freshUrl } : prev
              );
            }
            return freshUrl;
          }}
        />
      )}
    </div>
  );
}
