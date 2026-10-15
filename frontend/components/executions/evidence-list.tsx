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

  // Sort: group by stepId, then purpose, then newest
  const sorted = [...validEvidence].sort((a, b) => {
    const stepA = a.stepId || "";
    const stepB = b.stepId || "";
    if (stepA !== stepB) return stepA.localeCompare(stepB);

    const purposeOrder: Record<string, number> = {
      verification: 0,
      failure: 1,
      step_evidence: 2,
      discovery: 3,
      legacy: 4,
    };
    const pA = purposeOrder[a.purpose || ""] ?? 5;
    const pB = purposeOrder[b.purpose || ""] ?? 5;
    if (pA !== pB) return pA - pB;

    return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
  });

  return (
    <div className="space-y-2">
      {isDev && orphanScreenshots.length > 0 && (
        <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-amber-700 text-caption mb-3">
          Found {orphanScreenshots.length} orphan screenshot(s) — capture path bug.
        </div>
      )}
      <div className="space-y-1.5">
      {sorted.map((item) => (
        <button
          key={item.id}
          onClick={() => onEvidenceClick?.(item)}
          className={cn(
            "w-full flex items-center gap-3 rounded-xl border border-border bg-card/50 px-4 py-3 text-left transition-colors",
            "hover:bg-card hover:border-border/80",
            item.type === "SCREENSHOT" && "cursor-pointer"
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
              name={typeIcons[item.type] || "description"}
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
            <p className="text-caption text-muted-foreground">
              {typeLabels[item.type] || item.type}
              {item.description && (
                <span className="ml-1.5">— {item.description}</span>
              )}
            </p>
          </div>

          <div className="text-right shrink-0">
            <span className={cn("text-[11px] font-medium capitalize", statusColors[item.status] || "text-muted-foreground")}>
              {item.status === "VERIFIED" ? "Verified" : item.status === "CAPTURED" ? "Captured" : "Failed"}
            </span>
            <p className="text-[11px] text-muted-foreground/80 mt-0.5">
              {new Date(item.createdAt).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </p>
          </div>

          {item.type === "SCREENSHOT" && item.url && (
            <MaterialIcon
              name="open_in_new"
              size={14}
              className="text-muted-foreground/40 shrink-0"
            />
          )}
        </button>
      ))}
    </div>
  );
}
