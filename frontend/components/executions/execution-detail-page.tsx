"use client";

import { useState, useCallback, useEffect, useMemo, useTransition } from "react";
import { useRouter } from "next/navigation";
import type {
  ExecutionDetail as ExecutionDetailType,
  ActivityItem,
} from "@/lib/types";
import type { Evidence } from "@/lib/api/evidence";
import { useExecutionRealtime } from "@/hooks/use-execution-realtime";
import { cancelExecution, createExecution, getExecutionReport, mintShareableUrl, type ExecutionReport } from "@/lib/api/executions";
import { getApiBaseUrl } from "@/lib/api/client";
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
import { normalizeExecutionStatus } from "@/lib/executions/status";

const stepStatusLabels: Record<string, string> = {
  passed: "Passed",
  verified: "Verified",
  failed: "Failed",
  error: "Errored",
  unverified: "Unverified",
  pending: "Pending",
  skipped: "Skipped",
  incomplete: "Incomplete",
};

const stepStatusStyles: Record<string, string> = {
  passed: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700",
  verified: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700",
  failed: "border-destructive/30 bg-destructive/10 text-destructive",
  error: "border-destructive/30 bg-destructive/10 text-destructive",
  unverified: "border-amber-500/30 bg-amber-500/10 text-amber-700",
};

const stepCountOrder = ["passed", "verified", "failed", "error", "unverified", "pending", "skipped"];

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
  const [evidenceLoaded, setEvidenceLoaded] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<Evidence | null>(null);
  const [report, setReport] = useState<ExecutionReport | null>(null);
  const [reportLoaded, setReportLoaded] = useState(false);

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

  // Ordered screenshots for the step scrubber (deduped, by step index).
  const stepScreenshots = useMemo(() => {
    const seen = new Set<string>();
    const shots = evidence
      .filter((item) => item.type === "SCREENSHOT" && item.url)
      .filter((item) => {
        if (seen.has(item.url!)) return false;
        seen.add(item.url!);
        return true;
      })
      .map((item) => {
        const raw = item.metadata?.stepIndex ?? item.metadata?.step_index;
        const parsed = raw == null ? Number.NaN : Number(raw);
        return {
          url: item.url!,
          title: item.title || item.purpose || "",
          stepIndex: Number.isFinite(parsed) ? parsed : null,
          createdAt: item.createdAt || "",
        };
      });

    shots.sort((a, b) => {
      if (a.stepIndex != null && b.stepIndex != null) return a.stepIndex - b.stepIndex;
      return a.createdAt.localeCompare(b.createdAt);
    });

    return shots.map(({ url, title, stepIndex }) => ({ url, title, stepIndex }));
  }, [evidence]);

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

  const [shareLoading, setShareLoading] = useState(false);
  const [shareSuccess, setShareSuccess] = useState<string | null>(null);

  const handleShare = useCallback(async () => {
    setShareLoading(true);
    setShareSuccess(null);
    try {
      const res = await mintShareableUrl(execution.id);
      if (res?.url) {
        if (typeof navigator !== "undefined" && navigator.clipboard) {
          await navigator.clipboard.writeText(res.url);
        }
        setShareSuccess("Link copied to clipboard!");
        setTimeout(() => setShareSuccess(null), 3500);
      } else {
        setActionError("Could not generate shareable link.");
      }
    } catch {
      setActionError("Failed to generate shareable link.");
    } finally {
      setShareLoading(false);
    }
  }, [execution.id]);

  const handleExportPdf = useCallback(async () => {
    setActionError(null);
    const base = getApiBaseUrl();
    const reportPath = `${base}/api/v1/executions/${encodeURIComponent(execution.id)}/report`;
    const signature = report?.signature ?? (await getExecutionReport(execution.id))?.signature;

    if (!signature) {
      setActionError("Report is not ready yet. Reload the page and try again.");
      return;
    }

    window.open(
      `${reportPath}?signature=${encodeURIComponent(signature)}&format=html`,
      "_blank",
      "noopener,noreferrer"
    );
  }, [execution.id, report?.signature]);

  const displayError = actionError || streamError;
  const reportLoading = terminalStatuses.includes(execution.status) && !reportLoaded;
  const evidenceLoading = terminalStatuses.includes(execution.status) && !evidenceLoaded;

  const reportStatus = report?.status
    ? normalizeExecutionStatus(report.status)
    : execution.status === "completed" ? "unverified" : execution.status;
  const reportExecution = {
    ...execution,
    status: reportStatus,
    error: report?.diagnosis?.summary || execution.error,
  };

  useEffect(() => {
    if (!terminalStatuses.includes(execution.status)) return;
    let cancelled = false;
    getExecutionReport(execution.id)
      .then((value) => { if (!cancelled) setReport(value); })
      .finally(() => { if (!cancelled) setReportLoaded(true); });
    return () => { cancelled = true; };
  }, [execution.id, execution.status]);

  // Fetch evidence when execution reaches terminal state
  useEffect(() => {
    if (!terminalStatuses.includes(execution.status)) return;

    let cancelled = false;
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
        if (!cancelled) setEvidenceLoaded(true);
      });

    return () => { cancelled = true; };
  }, [execution.id, execution.status]);

  return (
    <div className="w-full max-w-5xl mx-auto space-y-6">
      {/* Header with Live Indicator */}
      <ExecutionHeader
        execution={reportExecution}
        connectionStatus={connectionStatus}
        onStopClick={() => setCancelOpen(true)}
        onRetryClick={handleRetry}
        isRetrying={isRetrying}
        onShareClick={handleShare}
        onExportPdfClick={handleExportPdf}
        isSharing={shareLoading}
        shareSuccess={shareSuccess}
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
        status={reportExecution.status}
        errorMessage={reportExecution.error}
        latestScreenshot={liveScreenshot}
        currentAction={currentAction}
        events={events}
        executionId={execution.id}
        stepScreenshots={stepScreenshots}
      />

      {/* 2-Column Section: Activity Stream + Result + Evidence */}
      <div className="grid gap-6 lg:grid-cols-3 pt-2">
        <div className="lg:col-span-2 space-y-4">
          {(() => {
            const destructiveEvent = events.find((e) => e.eventType === "safety.destructive_action_blocked");
            const isDestructiveBlocked = Boolean(
              destructiveEvent ||
              execution.status === "blocked" ||
              report?.failureCategory === "destructive_action_blocked"
            );
            if (!isDestructiveBlocked) return null;
            const payload = destructiveEvent?.payload as Record<string, unknown> | undefined;
            const targetLabel = String(payload?.target_label || payload?.action_type || "Destructive Action");
            const reason = String(payload?.reason || "This action is destructive and not in the project's allowlist.");
            return (
              <div className="rounded-xl border border-destructive/50 bg-destructive/10 p-4 text-destructive-foreground">
                <div className="flex items-start gap-3">
                  <MaterialIcon name="warning" size={20} className="text-destructive shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <h3 className="text-body-sm font-semibold text-destructive">
                      Execution BLOCKED: Destructive action prevented
                    </h3>
                    <p className="text-caption text-foreground/80">
                      Kova detected a destructive action and refused to execute it.
                    </p>
                    <p className="text-caption font-mono text-foreground/90">
                      Action: {targetLabel}
                    </p>
                    <p className="text-caption text-muted-foreground">
                      {reason}
                    </p>
                  </div>
                </div>
              </div>
            );
          })()}

          {(() => {
            const injectionEvent = events.find((e) => e.eventType === "safety.injection_attempt_detected");
            const isInjectionBlocked = Boolean(
              injectionEvent ||
              report?.failureCategory === "prompt_injection_detected"
            );
            if (!isInjectionBlocked) return null;
            const payload = injectionEvent?.payload as Record<string, unknown> | undefined;
            const evidence = String(payload?.evidence || "Untrusted instruction detected in page content.");
            return (
              <div className="rounded-xl border border-destructive/50 bg-destructive/10 p-4 text-destructive-foreground">
                <div className="flex items-start gap-3">
                  <MaterialIcon name="security" size={20} className="text-destructive shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <h3 className="text-body-sm font-semibold text-destructive">
                      SECURITY ALERT: Prompt injection attempt detected and blocked
                    </h3>
                    <p className="text-caption text-foreground/80">
                      The application under test contained instructions attempting to manipulate Kova&apos;s AI.
                    </p>
                    <p className="text-caption font-mono text-foreground/90">
                      Evidence: {evidence}
                    </p>
                  </div>
                </div>
              </div>
            );
          })()}

          <ExecutionActivity activities={activities} />
        </div>

        <div className="space-y-4">
          {(() => {
            const outcomeEvent = events.find((e) => e.eventType === "agent.loop_outcome");
            if (!outcomeEvent) return null;
            const payload = outcomeEvent.payload as Record<string, unknown> | undefined;
            const status = String(payload?.status || "COMPLETED");
            const reason = payload?.reason ? String(payload.reason) : null;
            return (
              <div className="rounded-xl border border-primary/40 bg-primary/10 p-3.5 text-foreground flex items-center gap-3">
                <MaterialIcon
                  name={status === "COMPLETED" ? "psychology" : "info"}
                  size={20}
                  className="text-primary shrink-0"
                />
                <div className="text-body-xs">
                  <span className="font-semibold text-primary">Agent outcome: {status}</span>
                  {status === "COMPLETED" && (
                    <span className="text-muted-foreground"> — verified by deterministic checker</span>
                  )}
                  {reason && <p className="text-caption text-foreground/80 mt-0.5">{reason}</p>}
                </div>
              </div>
            );
          })()}

          <ExecutionResult execution={reportExecution} />

          {/* Evidence Section */}
          {terminalStatuses.includes(execution.status) ? (
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
                  executionId={execution.id}
                  traceSignature={report?.signature}
                />
              )}
            </div>
          ) : null}
        </div>
      </div>

      {terminalStatuses.includes(execution.status) && (
        <section aria-label="Execution report" className="rounded-xl border border-border bg-card/50 p-4 sm:p-6 space-y-4">
          <div>
            <h2 className="text-heading font-semibold">Execution report</h2>
            <span className="text-caption text-muted-foreground">{reportLoading ? "Loading persisted report…" : report ? `Flow version ${execution.flowVersion ?? 1} · ${reportStatus.toUpperCase()}` : "Detailed report unavailable"}</span>
          </div>
          <div className="grid gap-2 text-caption text-muted-foreground sm:grid-cols-2">
            <p>Execution ID: <span className="font-mono text-foreground">{execution.id}</span></p>
            <p>Started: {execution.startedAt ? new Date(execution.startedAt).toLocaleString() : "Not recorded"}</p>
            <p>Completed: {execution.completedAt ? new Date(execution.completedAt).toLocaleString() : "Still in progress"}</p>
            <p>Result: {reportStatus === "completed" ? "Required outcomes verified" : "Not conclusively passed"}</p>
          </div>
          {report?.diagnosis && (
            <div className="rounded-lg border border-border bg-background/60 p-4 space-y-2">
              <h3 className="text-body-sm font-semibold">What Kova observed</h3>
              <p className="text-body-sm">{report.diagnosis.observed}</p>
              <p className="text-caption text-muted-foreground">Classification: {report.failureCategory?.replaceAll("_", " ") || "not classified"}. {report.diagnosis.reason}</p>
              <p className="text-body-sm"><strong>Next:</strong> {report.diagnosis.nextStep}</p>
              {report.diagnosis.hypothesis && <p className="text-caption text-muted-foreground">Hypothesis: {report.diagnosis.hypothesis}</p>}
            </div>
          )}
          {report && (
            <>
              <div className="flex flex-wrap gap-2 text-caption">
                {Object.entries(report.stepCounts)
                  .sort(([a], [b]) => {
                    const ai = stepCountOrder.indexOf(a);
                    const bi = stepCountOrder.indexOf(b);
                    return (ai === -1 ? stepCountOrder.length : ai) - (bi === -1 ? stepCountOrder.length : bi);
                  })
                  .map(([status, count]) => (
                    <span
                      key={status}
                      className={`rounded-md border px-2 py-1 font-medium ${stepStatusStyles[status] || "border-border text-muted-foreground"}`}
                    >
                      {count} {(stepStatusLabels[status] || status).toLowerCase()}
                    </span>
                  ))}
              </div>
              {report.steps.some((step) => step.status === "failed" || step.status === "unverified" || step.status === "error") && (
                <button type="button" onClick={() => {
                  const first = report.steps.findIndex((step) => step.status === "failed" || step.status === "unverified" || step.status === "error");
                  document.getElementById(`report-step-${first}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
                }} className="text-body-sm font-medium text-primary hover:underline">
                  Jump to first failed or unverified step
                </button>
              )}
              {report.steps.length ? (
                <ol className="space-y-2">
                  {report.steps.map((step, index) => (
                    <li id={`report-step-${index}`} key={String(step.stepId || index)} className="rounded-lg border border-border p-3 scroll-mt-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-body-sm font-medium">Step {Number(step.sequence ?? index) + 1}: {String(step.action || "Recorded action")}</span>
                        <span className={`rounded-md border px-2 py-0.5 text-caption font-medium ${stepStatusStyles[String(step.status)] || "border-border text-muted-foreground"}`}>
                          {stepStatusLabels[String(step.status)] || String(step.status || "Incomplete")}
                        </span>
                      </div>
                      {step.expected != null && <p className="mt-1 text-caption text-muted-foreground">Expected: {String(step.expected)}</p>}
                      {step.verification != null && (step.verification as Record<string, unknown>).observed != null && <p className="mt-1 text-caption text-muted-foreground">Observed: {String((step.verification as Record<string, unknown>).observed)}</p>}
                      {step.url != null && <p className="mt-1 text-caption font-mono text-muted-foreground break-all">{String(step.url)}</p>}
                      {step.verification != null && <p className="mt-1 text-caption">Verification: {String((step.verification as Record<string, unknown>).verdict || "inconclusive")}</p>}
                      {evidence.filter((item) => Number(item.metadata?.stepIndex) === Number(step.sequence) && item.type === "SCREENSHOT").map((item) => (
                        <button key={item.id} type="button" onClick={() => setSelectedEvidence(item)} className="mt-2 inline-flex items-center gap-1.5 text-caption text-primary hover:underline">
                          <MaterialIcon name="image" size={14} /> View step screenshot: {item.title}
                        </button>
                      ))}
                    </li>
                  ))}
                </ol>
              ) : <p className="text-body-sm text-muted-foreground">No step events were persisted for this execution.</p>}
            </>
          )}
          <div className="pt-3 border-t border-border/70">
            <span className="text-caption text-muted-foreground">
              {reportStatus === "completed"
                ? "Flow verified successfully. Use Run again in the header to test for regressions."
                : "Review observations, then use Run again in the header to retest with the latest updates."}
            </span>
          </div>
        </section>
      )}

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
          executionId={execution.id}
          traceSignature={report?.signature}
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
