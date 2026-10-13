"use client";

import React, { useState } from "react";
import type { ValidationRun } from "@/lib/types";
import { MaterialIcon } from "@/components/shared/material-icon";

interface ProjectValidationsProps {
  validations: ValidationRun[];
  projectId: string;
}

export function ProjectValidations({ validations, projectId }: ProjectValidationsProps) {
  const [showGuide, setShowGuide] = useState(false);

  return (
    <div className="rounded-xl border border-border bg-card/40 p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <MaterialIcon name="verified_user" size={20} className="text-primary" />
          <h3 className="text-body font-semibold text-foreground">Continuous Validation & CI</h3>
        </div>
        <button
          type="button"
          onClick={() => setShowGuide(!showGuide)}
          className="text-caption font-medium text-primary hover:underline inline-flex items-center gap-1"
        >
          <MaterialIcon name="terminal" size={14} />
          {showGuide ? "Hide CI Instructions" : "CI Setup & CLI"}
        </button>
      </div>

      {showGuide && (
        <div className="rounded-lg border border-border bg-background/80 p-4 space-y-3">
          <h4 className="text-body-sm font-semibold text-foreground">CI Integration & CLI Command</h4>
          <p className="text-caption text-muted-foreground leading-relaxed">
            Run risk-aware continuous validation on pull requests or preview builds. Kova analyzes changed files, selects impacted flows, and exits with authoritative codes (0: passed, 1: failed, 2: blocked/unverified, 3: config error, 4: service error).
          </p>
          <div className="rounded bg-muted p-3 font-mono text-[12px] text-foreground overflow-x-auto">
            <code>
              {`python3 scripts/kova_ci.py \\\n  --project-id "${projectId}" \\\n  --api-token "$KOVA_API_TOKEN" \\\n  --scope "targeted" \\\n  --changed-files "app/login/page.tsx,app/api/auth.py"`}
            </code>
          </div>
        </div>
      )}

      {validations.length === 0 ? (
        <p className="text-body-sm text-muted-foreground py-2">
          No continuous validation runs recorded yet. Trigger validation via CLI or GitHub Actions to see impact-aware regression history.
        </p>
      ) : (
        <div className="space-y-3">
          {validations.map((v) => {
            const isSuccess = v.exitCode === 0;
            const isFailed = v.exitCode === 1;
            const isWarning = v.exitCode === 2;

            return (
              <div key={v.id} className="rounded-lg border border-border/80 bg-background/50 p-3 space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-caption text-foreground">
                      {v.commitSha ? v.commitSha.slice(0, 8) : "Manual run"}
                    </span>
                    {v.branch && (
                      <span className="text-caption text-muted-foreground">({v.branch})</span>
                    )}
                    <span className="rounded bg-secondary px-2 py-0.5 text-caption uppercase text-secondary-foreground font-mono">
                      {v.scope}
                    </span>
                  </div>
                  <span
                    className={`rounded px-2 py-0.5 text-caption font-semibold ${
                      isSuccess
                        ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                        : isFailed
                        ? "bg-destructive/10 text-destructive"
                        : isWarning
                        ? "bg-amber-500/10 text-amber-700 dark:text-amber-400"
                        : "bg-secondary text-muted-foreground"
                    }`}
                  >
                    {v.status} {v.exitCode !== null ? `(Exit ${v.exitCode})` : ""}
                  </span>
                </div>

                {/* Summary counts & Baseline Diff */}
                <div className="flex flex-wrap items-center gap-3 text-caption text-muted-foreground">
                  <span>Tested: {v.summary.totalFlows ?? v.selectedFlowIds.length} flows</span>
                  {v.summary.passed ? <span className="text-emerald-600">{v.summary.passed} passed</span> : null}
                  {v.summary.failed ? <span className="text-destructive font-medium">{v.summary.failed} failed</span> : null}
                  {v.summary.blocked ? <span className="text-amber-600">{v.summary.blocked} blocked</span> : null}
                  {v.summary.unverified ? <span className="text-orange-600">{v.summary.unverified} unverified</span> : null}

                  {v.baselineDiff?.newlyFailing && v.baselineDiff.newlyFailing.length > 0 && (
                    <span className="text-destructive font-semibold">
                      +{v.baselineDiff.newlyFailing.length} regression(s)
                    </span>
                  )}
                  {v.baselineDiff?.recovered && v.baselineDiff.recovered.length > 0 && (
                    <span className="text-emerald-600 font-semibold">
                      +{v.baselineDiff.recovered.length} recovered
                    </span>
                  )}
                </div>

                {/* Impact Rationale */}
                {v.impactReport?.selectionReasons && Object.keys(v.impactReport.selectionReasons).length > 0 && (
                  <div className="text-caption text-muted-foreground border-t border-border/50 pt-2">
                    <span className="font-medium text-foreground">Why selected: </span>
                    {Object.values(v.impactReport.selectionReasons)[0]}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
