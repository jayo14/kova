"use client";

import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";
import { getTraceDownloadUrl, type Evidence } from "@/lib/api/evidence";

interface EvidenceListProps {
  evidence: Evidence[];
  onEvidenceClick?: (evidence: Evidence) => void;
  executionId?: string;
  traceSignature?: string | null;
}

const typeIcons: Record<string, string> = {
  SCREENSHOT: "photo_library",
  VERIFICATION: "verified",
  ARTIFACT: "description",
};

const typeLabels: Record<string, string> = {
  SCREENSHOT: "Screenshot",
  VERIFICATION: "Verification",
  ARTIFACT: "Artifact",
};

const statusLabels: Record<string, string> = {
  PENDING: "Pending",
  UPLOADED: "Uploaded",
  CAPTURED: "Captured",
  VERIFIED: "Verified",
  FAILED: "Failed",
};

/** Turn raw step ids like `mission-abc-step-2` into "Step 2". */
function humanizeStepLabel(stepId: string): string {
  if (stepId === "General") return "General evidence";
  const numbered = stepId.match(/step[-_](\d+)$/i);
  if (numbered) return `Step ${numbered[1]}`;
  if (/^step[-_]/i.test(stepId)) return stepId.replace(/^step[-_]+/i, "Step ");
  return stepId
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

const statusColors: Record<string, string> = {
  PENDING: "text-amber-500",
  UPLOADED: "text-muted-foreground",
  CAPTURED: "text-muted-foreground",
  VERIFIED: "text-emerald-600",
  FAILED: "text-destructive",
};

export function EvidenceList({ evidence, onEvidenceClick, executionId, traceSignature }: EvidenceListProps) {
  const isDev = process.env.NODE_ENV !== "production";
  const orphanScreenshots = evidence.filter(
    (item) => item.type === "SCREENSHOT" && !item.stepId && !item.purpose && item.purpose !== "legacy"
  );
  const validEvidence = evidence.filter(
    (item) => item.type !== "SCREENSHOT" || Boolean(item.stepId || item.purpose || item.purpose === "legacy")
  );

  if (validEvidence.length === 0) {
    return (
      <div className="text-center py-8">
        {isDev && orphanScreenshots.length > 0 && (
          <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-amber-700 text-caption mb-4">
            Found {orphanScreenshots.length} orphan screenshot(s) — capture path bug.
          </div>
        )}
        <MaterialIcon
          name="folder_open"
          size={32}
          className="mx-auto mb-3 text-muted-foreground/60"
        />
        <p className="text-body-sm text-muted-foreground font-medium">
          No evidence captured
        </p>
        <p className="text-caption text-muted-foreground/80 mt-1">
          The execution has no available evidence.
        </p>
      </div>
    );
  }

  // Group by stepId
  const stepGroups: { stepId: string; items: Evidence[] }[] = [];
  const groupMap = new Map<string, Evidence[]>();

  for (const item of validEvidence) {
    const sid = item.stepId || "General";
    if (!groupMap.has(sid)) {
      groupMap.set(sid, []);
    }
    groupMap.get(sid)!.push(item);
  }

  for (const [stepId, items] of groupMap.entries()) {
    items.sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime());
    stepGroups.push({ stepId, items });
  }

  return (
    <div className="space-y-6">
      {isDev && orphanScreenshots.length > 0 && (
        <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-amber-700 text-caption mb-3">
          Found {orphanScreenshots.length} orphan screenshot(s) — capture path bug.
        </div>
      )}

      {(() => {
        const traceItem = validEvidence.find((e) => e.traceUrl);
        if (!traceItem?.traceUrl) return null;
        const traceHref = executionId
          ? getTraceDownloadUrl(executionId, traceSignature)
          : traceItem.traceUrl;
        return (
          <div className="flex items-center justify-between gap-3 p-3 rounded-xl border border-border bg-card/80 text-body-sm">
            <div className="flex min-w-0 items-center gap-2 text-foreground">
              <MaterialIcon name="timeline" size={18} className="text-primary shrink-0" />
              <div className="min-w-0">
                <p className="font-medium">Playwright trace recording</p>
                <p className="text-caption text-muted-foreground">Full replay of every browser action, network call, and DOM snapshot.</p>
              </div>
            </div>
            <a
              href={traceHref ?? undefined}
              download
              className="inline-flex shrink-0 items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary/10 text-primary text-caption font-medium hover:bg-primary/20 transition-colors"
            >
              <MaterialIcon name="download" size={14} />
              <span>Download .zip</span>
            </a>
          </div>
        );
      })()}

      {stepGroups.map((group, groupIdx) => (
        <div key={group.stepId} className="relative pl-6 border-l-2 border-border/60 ml-3 space-y-3">
          {/* Timeline bullet */}
          <div className="absolute -left-[9px] top-1 h-4 w-4 rounded-full border-2 border-border bg-background flex items-center justify-center">
            <div className="h-1.5 w-1.5 rounded-full bg-primary" />
          </div>

          <div className="flex items-center justify-between">
            <h4 className="text-body-sm font-semibold text-foreground">
              {humanizeStepLabel(group.stepId)}
            </h4>
            <span className="text-[11px] text-muted-foreground/70">
              {group.items.length} {group.items.length === 1 ? "artifact" : "artifacts"}
            </span>
          </div>

          {/* Step Progression (Before & After states, Assertion, Network Errors) §Prompt D */}
          {(() => {
            const beforeItem = group.items.find((i) => i.kind === "before" || i.title.toLowerCase().includes("before"));
            const afterItem = group.items.find((i) => i.kind === "after" || i.title.toLowerCase().includes("after"));
            const assertionItem = group.items.find((i) => i.kind === "assertion" || i.type === "VERIFICATION");
            const failureItem = group.items.find((i) => i.kind === "failure" || i.status === "FAILED");
            const networkErrors = group.items.filter((i) => {
              const meta = i.metadata || {};
              return Boolean(meta.error || (Array.isArray(i.networkLog) && i.networkLog.length > 0));
            });

            if (!beforeItem && !afterItem && !assertionItem && !failureItem) return null;

            return (
              <div className="p-3 rounded-xl border border-border/80 bg-background/50 space-y-2.5">
                {(beforeItem || afterItem) && (
                  <div className="grid grid-cols-2 gap-2">
                    {beforeItem ? (
                      <div
                        onClick={() => onEvidenceClick?.(beforeItem)}
                        className="cursor-pointer group rounded-lg border border-border overflow-hidden bg-muted/30 p-1.5 transition-all hover:border-primary/40"
                      >
                        <div className="flex items-center justify-between text-[11px] font-medium text-muted-foreground mb-1 px-1">
                          <span>Before action</span>
                          <MaterialIcon name="visibility" size={12} className="opacity-0 group-hover:opacity-100 transition-opacity" />
                        </div>
                        {beforeItem.url ? (
                          <div className="aspect-video w-full rounded overflow-hidden bg-black/5 flex items-center justify-center">
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img src={beforeItem.url} alt="Before step" className="h-full w-full object-cover" />
                          </div>
                        ) : (
                          <div className="aspect-video w-full rounded bg-muted/40 flex items-center justify-center text-[10px] text-muted-foreground">
                            Screenshot pending
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="aspect-video rounded-lg border border-dashed border-border/60 flex items-center justify-center text-[11px] text-muted-foreground/60">
                        No before snapshot
                      </div>
                    )}

                    {afterItem ? (
                      <div
                        onClick={() => onEvidenceClick?.(afterItem)}
                        className="cursor-pointer group rounded-lg border border-border overflow-hidden bg-muted/30 p-1.5 transition-all hover:border-primary/40"
                      >
                        <div className="flex items-center justify-between text-[11px] font-medium text-muted-foreground mb-1 px-1">
                          <span>After action</span>
                          <MaterialIcon name="visibility" size={12} className="opacity-0 group-hover:opacity-100 transition-opacity" />
                        </div>
                        {afterItem.url ? (
                          <div className="aspect-video w-full rounded overflow-hidden bg-black/5 flex items-center justify-center">
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img src={afterItem.url} alt="After step" className="h-full w-full object-cover" />
                          </div>
                        ) : (
                          <div className="aspect-video w-full rounded bg-muted/40 flex items-center justify-center text-[10px] text-muted-foreground">
                            Screenshot pending
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="aspect-video rounded-lg border border-dashed border-border/60 flex items-center justify-center text-[11px] text-muted-foreground/60">
                        No after snapshot
                      </div>
                    )}
                  </div>
                )}

                {assertionItem && (
                  <div
                    onClick={() => onEvidenceClick?.(assertionItem)}
                    className="cursor-pointer flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-1.5 text-[12px] text-emerald-700 hover:bg-emerald-500/10 transition-colors"
                  >
                    <MaterialIcon name="verified" size={14} className="text-emerald-600 shrink-0" />
                    <span className="font-medium truncate">Supports assertion: {assertionItem.title}</span>
                  </div>
                )}

                {failureItem && (
                  <div
                    onClick={() => onEvidenceClick?.(failureItem)}
                    className="cursor-pointer flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-1.5 text-[12px] text-destructive hover:bg-destructive/10 transition-colors"
                  >
                    <MaterialIcon name="error" size={14} className="shrink-0" />
                    <span className="font-medium truncate">Step failure: {failureItem.description || failureItem.title}</span>
                  </div>
                )}
              </div>
            );
          })()}

          <div className="space-y-1.5">
            {group.items.map((item) => (
              <button
                key={item.id}
                onClick={() => onEvidenceClick?.(item)}
                className={cn(
                  "w-full flex items-center gap-3 rounded-xl border border-border bg-card/50 px-4 py-3 text-left transition-colors",
                  "hover:bg-card hover:border-border/80 cursor-pointer"
                )}
              >
                <div
                  className={cn(
                    "h-9 w-9 rounded-lg flex items-center justify-center shrink-0",
                    item.type === "VERIFICATION"
                      ? "bg-emerald-500/10"
                      : item.type === "SCREENSHOT"
                      ? "bg-primary/10"
                      : "bg-secondary"
                  )}
                >
                  <MaterialIcon
                    name={
                      item.videoUrl
                        ? "movie"
                        : item.type === "VERIFICATION"
                        ? "verified"
                        : item.type === "SCREENSHOT"
                        ? "photo_library"
                        : "description"
                    }
                    size={18}
                    className={cn(
                      item.type === "VERIFICATION"
                        ? "text-emerald-600"
                        : item.type === "SCREENSHOT"
                        ? "text-primary"
                        : "text-muted-foreground"
                    )}
                  />
                </div>

                <div className="flex-1 min-w-0">
                  <p className="text-body-sm font-medium text-foreground line-clamp-2">
                    {item.title}
                  </p>
                  <p className="text-caption text-muted-foreground truncate">
                    {typeLabels[item.type] || item.type}
                    {item.elementLocator && (
                      <span className="ml-1.5 font-mono text-[11px] text-muted-foreground/80">
                        [{item.elementLocator}]
                      </span>
                    )}
                    {item.description && (
                      <span className="ml-1.5">— {item.description}</span>
                    )}
                  </p>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  {item.domSnapshot && (
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                      DOM
                    </span>
                  )}
                  {item.a11yTree && (
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                      A11Y
                    </span>
                  )}
                  {Array.isArray(item.networkLog) && item.networkLog.length > 0 && (
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                      NET ({item.networkLog.length})
                    </span>
                  )}
                  {item.videoUrl && (
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-500">
                      VIDEO
                    </span>
                  )}
                  <span className={cn("text-[11px] font-medium", statusColors[item.status] || "text-muted-foreground")}>
                    {statusLabels[item.status] || item.status}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
