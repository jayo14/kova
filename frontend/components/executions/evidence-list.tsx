"use client";

import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";
import type { Evidence } from "@/lib/api/evidence";

interface EvidenceListProps {
  evidence: Evidence[];
  onEvidenceClick?: (evidence: Evidence) => void;
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

const statusColors: Record<string, string> = {
  CAPTURED: "text-muted-foreground",
  VERIFIED: "text-emerald-600",
  FAILED: "text-destructive",
};

export function EvidenceList({ evidence, onEvidenceClick }: EvidenceListProps) {
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

      {stepGroups.map((group, groupIdx) => (
        <div key={group.stepId} className="relative pl-6 border-l-2 border-border/60 ml-3 space-y-3">
          {/* Timeline bullet */}
          <div className="absolute -left-[9px] top-1 h-4 w-4 rounded-full border-2 border-border bg-background flex items-center justify-center">
            <div className="h-1.5 w-1.5 rounded-full bg-primary" />
          </div>

          <div className="flex items-center justify-between">
            <h4 className="text-body-sm font-semibold text-foreground">
              {group.stepId.startsWith("step_") ? `Step ${group.stepId.replace("step_", "")}` : group.stepId}
            </h4>
            <span className="text-[11px] text-muted-foreground/70">
              {group.items.length} {group.items.length === 1 ? "artifact" : "artifacts"}
            </span>
          </div>

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
                  <p className="text-body-sm font-medium text-foreground truncate">
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
                  <span className={cn("text-[11px] font-medium capitalize", statusColors[item.status] || "text-muted-foreground")}>
                    {item.status === "VERIFIED" ? "Verified" : item.status === "CAPTURED" ? "Captured" : "Failed"}
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
