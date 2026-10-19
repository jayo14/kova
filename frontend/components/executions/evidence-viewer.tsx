"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";
import type { Evidence } from "@/lib/api/evidence";

interface EvidenceViewerProps {
  evidence: Evidence | null;
  compareEvidence?: Evidence | null;
  open: boolean;
  onClose: () => void;
  onRefreshUrl?: (evidenceId: string) => Promise<string | null>;
}

type TabType = "screenshot" | "dom" | "a11y" | "network" | "video" | "trace" | "verification" | "visual_diff";

export function EvidenceViewer({
  evidence,
  compareEvidence,
  open,
  onClose,
  onRefreshUrl,
}: EvidenceViewerProps) {
  const [activeTab, setActiveTab] = useState<TabType>("screenshot");
  const [imgLoaded, setImgLoaded] = useState(false);
  const [imgError, setImgError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [currentUrl, setCurrentUrl] = useState<string | null>(null);
  const retriedRef = useRef(false);

  // Available tabs
  const availableTabs = useMemo(() => {
    if (!evidence) return [];
    const tabs: TabType[] = [];
    if (evidence.metadata?.visual_result || evidence.metadata?.visualResult || evidence.type === "VISUAL" || compareEvidence) {
      tabs.push("visual_diff");
    }
    if (evidence.url || evidence.type === "SCREENSHOT") tabs.push("screenshot");
    if (evidence.domSnapshot) tabs.push("dom");
    if (evidence.a11yTree) tabs.push("a11y");
    if (evidence.networkLog && (Array.isArray(evidence.networkLog) ? evidence.networkLog.length > 0 : true)) {
      tabs.push("network");
    }
    if (evidence.videoUrl) tabs.push("video");
    tabs.push("trace");
    if (evidence.type === "VERIFICATION" || evidence.metadata?.checks || evidence.note) {
      tabs.push("verification");
    }
    return tabs.length > 0 ? tabs : (["screenshot"] as TabType[]);
  }, [evidence, compareEvidence]);

  useEffect(() => {
    if (open && evidence) {
      setImgLoaded(false);
      setImgError(false);
      setRefreshing(false);
      setCurrentUrl(evidence.url || null);
      retriedRef.current = false;
      if (evidence.type === "VERIFICATION") {
        setActiveTab("verification");
      } else if (evidence.url) {
        setActiveTab("screenshot");
      } else if (evidence.videoUrl) {
        setActiveTab("video");
      } else if (availableTabs[0]) {
        setActiveTab(availableTabs[0]);
      }
    }
  }, [open, evidence, availableTabs]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose]
  );

  useEffect(() => {
    if (!open) return;
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, handleKeyDown]);

  const handleImageError = useCallback(async () => {
    if (retriedRef.current || !onRefreshUrl || !evidence) {
      setImgError(true);
      return;
    }

    retriedRef.current = true;
    setRefreshing(true);

    try {
      const freshUrl = await onRefreshUrl(evidence.id);
      if (freshUrl) {
        setCurrentUrl(freshUrl);
        setImgError(false);
        setRefreshing(false);
        return;
      }
    } catch {
      // refresh failed
    }

    setRefreshing(false);
    setImgError(true);
  }, [onRefreshUrl, evidence]);

  if (!open || !evidence) return null;

  const checks = Array.isArray(evidence.metadata?.checks)
    ? (evidence.metadata.checks as Array<{ type: string; passed: boolean; message?: string }>)
    : [];

  const visualResult = (evidence.metadata?.visual_result || evidence.metadata?.visualResult || {}) as {
    overall_status?: string;
    pixel_diff_percentage?: number;
    layout_diff_count?: number;
    a11y_diff_count?: number;
    defects?: Array<{
      type: string;
      severity: string;
      description: string;
      bounding_box?: { x: number; y: number; width: number; height: number };
      confidence?: number;
    }>;
    vlm_assessment?: string;
    vlm_confidence?: number;
    reference_screenshot_url?: string;
    diff_image_url?: string;
  };

  // Parse DOM snapshot if serialized JSON {before, after}
  let domBefore: string | null = null;
  let domAfter: string | null = null;
  if (evidence.domSnapshot) {
    try {
      const parsed = JSON.parse(evidence.domSnapshot);
      if (typeof parsed === "object" && parsed !== null && ("before" in parsed || "after" in parsed)) {
        domBefore = parsed.before || null;
        domAfter = parsed.after || null;
      } else {
        domAfter = evidence.domSnapshot;
      }
    } catch {
      domAfter = evidence.domSnapshot;
    }
  }

  // Parse a11y tree formatted
  let formattedA11y: string | null = null;
  if (evidence.a11yTree) {
    try {
      const parsed = JSON.parse(evidence.a11yTree);
      formattedA11y = JSON.stringify(parsed, null, 2);
    } catch {
      formattedA11y = evidence.a11yTree;
    }
  }

  // Network logs
  const networkLogs = Array.isArray(evidence.networkLog)
    ? (evidence.networkLog as Array<Record<string, unknown>>)
    : [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/75 backdrop-blur-sm" onClick={onClose} />
      <div className="relative flex flex-col max-w-4xl w-full max-h-[90vh] bg-background border border-border rounded-2xl shadow-2xl overflow-hidden z-10">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-card/60">
          <div className="flex items-center gap-3 min-w-0">
            <div className="h-9 w-9 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
              <MaterialIcon name="photo_library" size={18} className="text-primary" />
            </div>
            <div className="min-w-0">
              <h3 className="text-body-sm font-semibold text-foreground truncate">
                {evidence.title}
              </h3>
              <p className="text-[12px] text-muted-foreground truncate">
                {evidence.stepId ? `Step: ${evidence.stepId}` : "Execution Evidence"}
                {evidence.elementLocator && ` • locator: ${evidence.elementLocator}`}
                {evidence.purpose && ` • ${evidence.purpose}`}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
            >
              <MaterialIcon name="close" size={18} />
            </button>
          </div>
        </div>

        {/* Tab Bar */}
        <div className="flex items-center gap-1 px-6 border-b border-border bg-muted/20 overflow-x-auto">
          {availableTabs.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "flex items-center gap-1.5 px-3.5 py-2.5 text-caption font-medium border-b-2 transition-colors capitalize",
                activeTab === tab
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
              )}
            >
              <MaterialIcon
                name={
                  tab === "visual_diff"
                    ? "compare"
                    : tab === "screenshot"
                    ? "image"
                    : tab === "dom"
                    ? "code"
                    : tab === "a11y"
                    ? "accessibility"
                    : tab === "network"
                    ? "wifi"
                    : tab === "video"
                    ? "movie"
                    : tab === "trace"
                    ? "timeline"
                    : "verified"
                }
                size={16}
              />
              <span>{tab === "visual_diff" ? "Visual Diff" : tab}</span>
            </button>
          ))}
        </div>

        {/* Tab Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {activeTab === "screenshot" && (
            <div className="space-y-4">
              {compareEvidence ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Current Run */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-caption font-semibold">
                      <span className="text-foreground">Current Run</span>
                      <span className="text-muted-foreground">{evidence.title}</span>
                    </div>
                    <div className="relative w-full rounded-xl overflow-hidden border border-border bg-black">
                      {currentUrl ? (
                        <img
                          src={currentUrl}
                          alt="Current Run Evidence"
                          className="w-full h-auto max-h-[50vh] object-contain"
                          onError={handleImageError}
                        />
                      ) : (
                        <div className="py-12 text-center text-muted-foreground text-caption">No screenshot</div>
                      )}
                    </div>
                  </div>

                  {/* Compare Run */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-caption font-semibold">
                      <span className="text-primary">Compare Run (Baseline)</span>
                      <span className="text-muted-foreground">{compareEvidence.title}</span>
                    </div>
                    <div className="relative w-full rounded-xl overflow-hidden border border-border bg-black">
                      {compareEvidence.url ? (
                        <img
                          src={compareEvidence.url}
                          alt="Compare Run Evidence"
                          className="w-full h-auto max-h-[50vh] object-contain"
                        />
                      ) : (
                        <div className="py-12 text-center text-muted-foreground text-caption">No screenshot in compare run</div>
                      )}
                    </div>
                  </div>
                </div>
              ) : currentUrl ? (
                <div className="relative w-full rounded-xl overflow-hidden border border-border bg-black">
                  {imgError ? (
                    <div className="flex flex-col items-center justify-center py-16 text-foreground">
                      <MaterialIcon name="broken_image" size={48} className="mb-3 opacity-60" />
                      <p className="text-body-sm font-medium">Evidence image could not be loaded.</p>
                      <p className="text-caption text-muted-foreground mt-1">The signed URL may have expired.</p>
                      {onRefreshUrl && (
                        <button
                          onClick={async () => {
                            retriedRef.current = false;
                            setImgError(false);
                            setRefreshing(true);
                            try {
                              const freshUrl = await onRefreshUrl(evidence.id);
                              if (freshUrl) {
                                setCurrentUrl(freshUrl);
                                retriedRef.current = true;
                              } else {
                                setImgError(true);
                              }
                            } catch {
                              setImgError(true);
                            }
                            setRefreshing(false);
                          }}
                          className="mt-3 text-caption text-primary hover:underline"
                          disabled={refreshing}
                        >
                          {refreshing ? "Refreshing..." : "Try again"}
                        </button>
                      )}
                    </div>
                  ) : (
                    <>
                      {(refreshing || !imgLoaded) && (
                        <div className="flex items-center justify-center py-16">
                          <MaterialIcon name="progress_activity" size={24} className="animate-spin text-muted-foreground" />
                        </div>
                      )}
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={currentUrl}
                        alt={evidence.title}
                        className={cn(
                          "w-full h-auto max-h-[60vh] object-contain",
                          !imgLoaded && "hidden"
                        )}
                        onLoad={() => setImgLoaded(true)}
                        onError={handleImageError}
                      />
                    </>
                  )}
                </div>
              ) : (
                <div className="p-8 text-center border border-dashed border-border rounded-xl">
                  <MaterialIcon name="image_not_supported" size={40} className="mx-auto mb-2 text-muted-foreground/60" />
                  <p className="text-body-sm text-muted-foreground">No screenshot artifact available for this step.</p>
                </div>
              )}

              {evidence.elementLocator && (
                <div className="p-3 bg-muted/40 border border-border rounded-lg text-caption flex items-center justify-between">
                  <span className="text-muted-foreground">Target Element Locator:</span>
                  <code className="font-mono text-primary bg-background px-2 py-0.5 rounded border border-border">
                    {evidence.elementLocator}
                  </code>
                </div>
              )}
            </div>
          )}

          {activeTab === "dom" && (
            <div className="space-y-4">
              {domBefore && domAfter ? (
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <h4 className="text-caption font-semibold text-muted-foreground mb-1">DOM Before Action</h4>
                    <pre className="p-4 rounded-xl border border-border bg-muted/30 text-[11px] font-mono max-h-[50vh] overflow-auto whitespace-pre-wrap">
                      {domBefore}
                    </pre>
                  </div>
                  <div>
                    <h4 className="text-caption font-semibold text-muted-foreground mb-1">DOM After Action</h4>
                    <pre className="p-4 rounded-xl border border-border bg-muted/30 text-[11px] font-mono max-h-[50vh] overflow-auto whitespace-pre-wrap">
                      {domAfter}
                    </pre>
                  </div>
                </div>
              ) : domAfter ? (
                <div>
                  <h4 className="text-caption font-semibold text-muted-foreground mb-1">DOM Snapshot</h4>
                  <pre className="p-4 rounded-xl border border-border bg-muted/30 text-[11px] font-mono max-h-[55vh] overflow-auto whitespace-pre-wrap">
                    {domAfter}
                  </pre>
                </div>
              ) : (
                <p className="text-body-sm text-muted-foreground">No DOM snapshot recorded for this run.</p>
              )}
            </div>
          )}

          {activeTab === "a11y" && (
            <div className="space-y-2">
              <h4 className="text-caption font-semibold text-muted-foreground mb-1">Accessibility Tree (AI View)</h4>
              {formattedA11y ? (
                <pre className="p-4 rounded-xl border border-border bg-muted/30 text-[11px] font-mono max-h-[55vh] overflow-auto whitespace-pre-wrap">
                  {formattedA11y}
                </pre>
              ) : (
                <p className="text-body-sm text-muted-foreground">No accessibility tree captured.</p>
              )}
            </div>
          )}

          {activeTab === "network" && (
            <div className="space-y-2">
              <h4 className="text-caption font-semibold text-muted-foreground mb-1">Network Activity During Step</h4>
              {networkLogs.length > 0 ? (
                <div className="rounded-xl border border-border overflow-hidden">
                  <table className="w-full text-left text-[12px]">
                    <thead className="bg-muted/40 border-b border-border text-muted-foreground font-medium">
                      <tr>
                        <th className="px-3 py-2">Method</th>
                        <th className="px-3 py-2">Status</th>
                        <th className="px-3 py-2">URL</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {networkLogs.map((log, idx) => {
                        const status = Number(log.status || 0);
                        return (
                          <tr key={idx} className="hover:bg-muted/20 font-mono">
                            <td className="px-3 py-2 text-foreground font-semibold">
                              {String(log.method || "GET")}
                            </td>
                            <td className="px-3 py-2">
                              <span
                                className={cn(
                                  "px-1.5 py-0.5 rounded text-[10px] font-semibold",
                                  status >= 400
                                    ? "bg-destructive/10 text-destructive"
                                    : "bg-emerald-500/10 text-emerald-600"
                                )}
                              >
                                {status || "—"}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-muted-foreground truncate max-w-md">
                              {String(log.url || "")}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-body-sm text-muted-foreground">No network requests observed during this step.</p>
              )}
            </div>
          )}

          {activeTab === "video" && (
            <div className="space-y-4">
              {evidence.videoUrl ? (
                <div className="rounded-xl border border-border overflow-hidden bg-black flex justify-center">
                  <video
                    src={evidence.videoUrl}
                    controls
                    className="max-h-[60vh] w-auto"
                  />
                </div>
              ) : (
                <p className="text-body-sm text-muted-foreground">Video recording not available for this run.</p>
              )}
              {evidence.timestampRange && (
                <p className="text-caption text-muted-foreground">
                  Step window: {evidence.timestampRange[0]?.toFixed(2)}s - {evidence.timestampRange[1]?.toFixed(2)}s
                </p>
              )}
            </div>
          )}

          {activeTab === "trace" && (
            <div className="space-y-4">
              {evidence.traceUrl ? (
                <div className="space-y-4">
                  <div className="p-4 rounded-xl border border-border bg-card/60 flex items-center justify-between">
                    <div className="space-y-1">
                      <div className="text-body-sm font-semibold text-foreground flex items-center gap-2">
                        <MaterialIcon name="timeline" size={18} className="text-primary" />
                        Playwright Execution Trace
                      </div>
                      <p className="text-caption text-muted-foreground">
                        Inspect recorded browser actions, console messages, network events, and DOM snapshots in Playwright Trace Viewer.
                      </p>
                    </div>
                    <a
                      href={evidence.traceUrl}
                      download
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90 transition-colors"
                    >
                      <MaterialIcon name="download" size={16} />
                      Download Trace
                    </a>
                  </div>

                  <div className="p-4 rounded-xl border border-border/80 bg-secondary/10 space-y-2 text-caption">
                    <div className="font-semibold text-foreground">How to inspect locally:</div>
                    <code className="block bg-black/80 text-emerald-400 p-2.5 rounded-lg font-mono text-xs select-all">
                      npx playwright show-trace &lt;downloaded-trace.zip&gt;
                    </code>
                    <p className="text-muted-foreground text-[11px]">
                      Or open{" "}
                      <a
                        href="https://trace.playwright.dev"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary underline"
                      >
                        trace.playwright.dev
                      </a>{" "}
                      in your browser and drag-and-drop the trace file.
                    </p>
                  </div>
                </div>
              ) : (
                <div className="p-8 text-center space-y-3 rounded-2xl border border-dashed border-border bg-card/30">
                  <div className="h-10 w-10 mx-auto rounded-full bg-muted flex items-center justify-center text-muted-foreground">
                    <MaterialIcon name="timeline" size={20} />
                  </div>
                  <div className="text-body-sm font-semibold text-foreground">No Playwright Trace Recorded</div>
                  <p className="text-caption text-muted-foreground max-w-md mx-auto">
                    Full execution tracing can be enabled by setting <code className="px-1.5 py-0.5 rounded bg-muted font-mono text-xs text-foreground">EVIDENCE_CAPTURE_TRACE=true</code> in your environment.
                  </p>
                </div>
              )}
            </div>
          )}

          {activeTab === "verification" && (
            <div className="space-y-4">
              <div className="flex items-start gap-3 p-4 bg-emerald-500/5 border border-emerald-500/20 rounded-xl">
                <MaterialIcon name="verified" size={24} className="text-emerald-600 shrink-0 mt-0.5" />
                <div>
                  <h4 className="text-body-sm font-semibold text-foreground">{evidence.title}</h4>
                  {evidence.note && (
                    <p className="text-caption text-muted-foreground mt-1 font-mono">
                      {evidence.note}
                    </p>
                  )}
                  {evidence.description && (
                    <p className="text-caption text-muted-foreground mt-1">
                      {evidence.description}
                    </p>
                  )}
                </div>
              </div>

              {checks.length > 0 && (
                <div className="space-y-2">
                  <h5 className="text-caption font-semibold text-foreground">Executed Checks</h5>
                  <div className="space-y-1.5">
                    {checks.map((chk, i) => (
                      <div
                        key={i}
                        className={cn(
                          "flex items-center gap-2 px-3 py-2 rounded-lg text-caption border",
                          chk.passed
                            ? "bg-emerald-500/5 border-emerald-500/20 text-emerald-700"
                            : "bg-destructive/5 border-destructive/20 text-destructive"
                        )}
                      >
                        <MaterialIcon name={chk.passed ? "check_circle" : "cancel"} size={16} />
                        <span className="font-medium font-mono">{chk.type}:</span>
                        <span>{chk.message || (chk.passed ? "Check passed" : "Check failed")}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === "visual_diff" && (
            <div className="space-y-6">
              {/* Visual Metrics Overview */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="rounded-xl border border-border bg-card/60 p-3 space-y-1">
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Status</div>
                  <div className="flex items-center gap-1.5 font-semibold text-body-sm">
                    {(() => {
                      const st = (visualResult.overall_status || (visualResult.defects?.length ? "failed" : "passed")).toLowerCase();
                      if (st === "passed") return <span className="text-emerald-400">Passed</span>;
                      if (st === "failed") return <span className="text-destructive">Failed</span>;
                      return <span className="text-amber-400">Unverified</span>;
                    })()}
                  </div>
                </div>

                <div className="rounded-xl border border-border bg-card/60 p-3 space-y-1">
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Pixel Diff</div>
                  <div className="font-mono font-semibold text-body-sm text-foreground">
                    {visualResult.pixel_diff_percentage !== undefined ? `${visualResult.pixel_diff_percentage.toFixed(2)}%` : "0.00%"}
                  </div>
                </div>

                <div className="rounded-xl border border-border bg-card/60 p-3 space-y-1">
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Layout Regions</div>
                  <div className="font-mono font-semibold text-body-sm text-foreground">
                    {visualResult.layout_diff_count ?? 0}
                  </div>
                </div>

                <div className="rounded-xl border border-border bg-card/60 p-3 space-y-1">
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">A11y Tree Diff</div>
                  <div className="font-mono font-semibold text-body-sm text-foreground">
                    {visualResult.a11y_diff_count ?? 0}
                  </div>
                </div>
              </div>

              {/* VLM Assessment Callout if available */}
              {visualResult.vlm_assessment && (
                <div className="p-4 rounded-xl border border-purple-500/20 bg-purple-500/5 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-purple-400 font-semibold text-caption">
                      <MaterialIcon name="psychology" size={18} />
                      <span>VLM Semantic Assessment</span>
                    </div>
                    {visualResult.vlm_confidence && (
                      <span className="text-[11px] font-mono text-purple-400/80">
                        confidence: {(visualResult.vlm_confidence * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                  <p className="text-body-sm text-foreground leading-relaxed">
                    {visualResult.vlm_assessment}
                  </p>
                </div>
              )}

              {/* Screenshots Tri-View: Baseline | Diff Overlay | Current */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {/* Baseline */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-caption font-semibold">
                    <span className="text-primary">Baseline Reference</span>
                  </div>
                  <div className="relative w-full rounded-xl overflow-hidden border border-border bg-black aspect-video flex items-center justify-center">
                    {(visualResult.reference_screenshot_url || compareEvidence?.url) ? (
                      <img
                        src={visualResult.reference_screenshot_url || compareEvidence?.url || ""}
                        alt="Baseline Screenshot"
                        className="w-full h-full object-contain"
                      />
                    ) : (
                      <span className="text-muted-foreground text-caption">No baseline image</span>
                    )}
                  </div>
                </div>

                {/* Diff Overlay */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-caption font-semibold">
                    <span className="text-destructive">Diff Overlay (Pixel Shifts)</span>
                  </div>
                  <div className="relative w-full rounded-xl overflow-hidden border border-border bg-black aspect-video flex items-center justify-center">
                    {visualResult.diff_image_url ? (
                      <img
                        src={visualResult.diff_image_url}
                        alt="Pixel Diff Overlay"
                        className="w-full h-full object-contain"
                      />
                    ) : (
                      <span className="text-muted-foreground text-caption">No diff overlay</span>
                    )}
                  </div>
                </div>

                {/* Current Run */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-caption font-semibold">
                    <span className="text-foreground">Current Render</span>
                  </div>
                  <div className="relative w-full rounded-xl overflow-hidden border border-border bg-black aspect-video flex items-center justify-center">
                    {currentUrl ? (
                      <img
                        src={currentUrl}
                        alt="Current Run Screenshot"
                        className="w-full h-full object-contain"
                      />
                    ) : (
                      <span className="text-muted-foreground text-caption">No current image</span>
                    )}
                  </div>
                </div>
              </div>

              {/* Detected Defects List */}
              {visualResult.defects && visualResult.defects.length > 0 && (
                <div className="space-y-3 pt-2">
                  <h4 className="text-caption font-semibold uppercase tracking-wider text-muted-foreground">
                    Detected Visual Defects ({visualResult.defects.length})
                  </h4>
                  <div className="space-y-2">
                    {visualResult.defects.map((defect, i) => (
                      <div
                        key={i}
                        className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 rounded-lg border border-border bg-background/50"
                      >
                        <div className="flex items-start sm:items-center gap-2">
                          <span
                            className={cn(
                              "text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded border",
                              defect.severity === "high"
                                ? "bg-destructive/10 border-destructive/30 text-destructive"
                                : defect.severity === "medium"
                                ? "bg-amber-500/10 border-amber-500/30 text-amber-400"
                                : "bg-blue-500/10 border-blue-500/30 text-blue-400"
                            )}
                          >
                            {defect.severity}
                          </span>
                          <span className="font-mono text-caption text-primary">{defect.type}</span>
                          <span className="text-caption text-foreground">{defect.description}</span>
                        </div>
                        {defect.bounding_box && (
                          <span className="font-mono text-[11px] text-muted-foreground shrink-0">
                            {defect.bounding_box.width}x{defect.bounding_box.height}px at ({defect.bounding_box.x}, {defect.bounding_box.y})
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-3 border-t border-border bg-card/40 text-caption text-muted-foreground">
          <span>Type: {evidence.type}</span>
          <span>Captured: {new Date(evidence.createdAt).toLocaleTimeString()}</span>
        </div>
      </div>
    </div>
  );
}
