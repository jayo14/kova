"use client";

import { useState } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";

type EvidenceTab = "timeline" | "screenshots" | "actions" | "result";

const evidenceActions = [
  { text: "Opened application", time: "0.4s", type: "navigate" },
  { text: "Signed in with test credentials", time: "4.8s", type: "auth" },
  { text: "Opened materials repository", time: "11.2s", type: "click" },
  { text: "Uploaded biology document", time: "19.5s", type: "upload" },
  { text: "Generated 10-question quiz", time: "36.2s", type: "generate" },
  { text: "Verified completion and output", time: "42.0s", type: "verify" },
];

const stats = [
  { value: "42s", label: "Duration" },
  { value: "6", label: "Actions executed" },
  { value: "1", label: "Verification" },
];

export function EvidenceSection() {
  const [activeTab, setActiveTab] = useState<EvidenceTab>("timeline");

  return (
    <section id="developers" className="py-24 md:py-32 border-t border-border/80">
      <div className="mx-auto max-w-6xl px-6">
        {/* Section Header */}
        <div className="max-w-2xl mb-16 md:mb-20">
          <span className="text-label text-muted-foreground mb-3 block">
            Verification
          </span>
          <h2 className="text-h1 md:text-[2.75rem] md:leading-tight text-foreground mb-4 tracking-tight">
            Every journey leaves evidence.
          </h2>
          <p className="text-body-lg text-muted-foreground">
            Kova doesn&apos;t just say &ldquo;done.&rdquo; It records every step, captures every transition, and proves what happened.
          </p>
        </div>

        {/* Evidence Dashboard Frame */}
        <div className="rounded-2xl border border-border bg-card shadow-xs overflow-hidden">
          {/* Top Bar / Status */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border bg-secondary/30 px-6 py-4">
            <div>
              <span className="text-label text-muted-foreground font-mono">
                EXECUTION COMPLETE
              </span>
              <p className="text-body font-semibold text-foreground mt-0.5">
                Generate quiz from PDF
              </p>
            </div>

            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 text-primary px-3 py-1 text-caption font-semibold">
                <MaterialIcon name="verified" size={15} />
                Passed
              </span>
              <span className="text-mono text-caption text-muted-foreground">
                id: ex_9b4f2c
              </span>
            </div>
          </div>

          {/* Core Visual Body: Checklist + Stats */}
          <div className="grid grid-cols-1 lg:grid-cols-12 divide-y lg:divide-y-0 lg:divide-x divide-border">
            {/* Action Checklist (Left 7 Cols) */}
            <div className="lg:col-span-7 p-6 md:p-8">
              <p className="text-caption text-muted-foreground uppercase font-mono tracking-wider mb-4">
                Verified milestone checklist
              </p>

              <div className="space-y-3">
                {evidenceActions.map((action, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between p-3 rounded-xl border border-border/60 bg-background/60"
                  >
                    <div className="flex items-center gap-3">
                      <MaterialIcon
                        name="check_circle"
                        size={18}
                        className="text-primary shrink-0"
                      />
                      <span className="text-body-sm text-foreground font-medium">
                        {action.text}
                      </span>
                    </div>
                    <span className="text-mono text-caption text-muted-foreground">
                      +{action.time}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Execution Metrics (Right 5 Cols) */}
            <div className="lg:col-span-5 p-6 md:p-8 flex flex-col justify-between bg-secondary/15">
              <div>
                <p className="text-caption text-muted-foreground uppercase font-mono tracking-wider mb-4">
                  Run Metrics
                </p>

                <div className="space-y-6">
                  {stats.map((stat) => (
                    <div key={stat.label} className="border-b border-border/50 pb-4 last:border-0 last:pb-0">
                      <span className="text-display sm:text-[2.75rem] text-primary font-bold tracking-tight block">
                        {stat.value}
                      </span>
                      <span className="text-body-sm text-muted-foreground">
                        {stat.label}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-8 pt-6 border-t border-border/70">
                <p className="text-caption text-muted-foreground">
                  Artifacts signed with SHA-256 integrity checks.
                </p>
              </div>
            </div>
          </div>

          {/* Interactive Foreshadowing Tabs */}
          <div className="border-t border-border bg-background">
            <div className="flex items-center gap-1 px-6 pt-3 border-b border-border/60 overflow-x-auto">
              {(["timeline", "screenshots", "actions", "result"] as EvidenceTab[]).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setActiveTab(tab)}
                  className={cn(
                    "px-4 py-2 text-body-sm font-medium border-b-2 transition-all capitalize -mb-px whitespace-nowrap",
                    activeTab === tab
                      ? "border-primary text-primary font-semibold"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  )}
                >
                  {tab}
                </button>
              ))}
            </div>

            <div className="p-6">
              {activeTab === "timeline" && (
                <div className="space-y-2 text-mono text-body-sm">
                  <div className="flex items-start gap-4 p-2 rounded hover:bg-secondary/20">
                    <span className="text-caption text-primary shrink-0 w-16">00:00.40</span>
                    <span className="text-foreground font-medium">Session initialized</span>
                    <span className="text-muted-foreground text-caption ml-auto hidden sm:inline">Chromium 122.0</span>
                  </div>
                  <div className="flex items-start gap-4 p-2 rounded hover:bg-secondary/20">
                    <span className="text-caption text-primary shrink-0 w-16">00:04.82</span>
                    <span className="text-foreground">Authentication accepted (token cached)</span>
                    <span className="text-muted-foreground text-caption ml-auto hidden sm:inline">200 OK</span>
                  </div>
                  <div className="flex items-start gap-4 p-2 rounded hover:bg-secondary/20">
                    <span className="text-caption text-primary shrink-0 w-16">00:19.55</span>
                    <span className="text-foreground">Uploaded &apos;bio-notes.pdf&apos; (1.2MB)</span>
                    <span className="text-muted-foreground text-caption ml-auto hidden sm:inline">Completed</span>
                  </div>
                  <div className="flex items-start gap-4 p-2 rounded hover:bg-secondary/20">
                    <span className="text-caption text-primary shrink-0 w-16">00:36.21</span>
                    <span className="text-foreground">Generated 10 questions</span>
                    <span className="text-muted-foreground text-caption ml-auto hidden sm:inline">10 items</span>
                  </div>
                  <div className="flex items-start gap-4 p-2 rounded hover:bg-secondary/20">
                    <span className="text-caption text-primary shrink-0 w-16">00:42.00</span>
                    <span className="text-primary font-semibold">Assertion verified: Quiz UI rendered</span>
                    <span className="text-primary text-caption ml-auto hidden sm:inline">PASSED</span>
                  </div>
                </div>
              )}

              {activeTab === "screenshots" && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  {["01 Login", "02 Upload", "03 Processing", "04 Quiz Result"].map((title, i) => (
                    <div key={title} className="rounded-xl border border-border bg-secondary/30 p-3 space-y-2">
                      <div className="h-24 rounded-lg bg-background border border-border/60 flex items-center justify-center">
                        <MaterialIcon name="image" size={24} className="text-muted-foreground/50" />
                      </div>
                      <p className="text-caption text-foreground font-medium truncate">{title}</p>
                      <span className="text-[10px] text-muted-foreground font-mono block">Step {i + 1}</span>
                    </div>
                  ))}
                </div>
              )}

              {activeTab === "actions" && (
                <div className="space-y-2 font-mono text-caption sm:text-body-sm">
                  <div className="grid grid-cols-12 gap-2 text-muted-foreground border-b border-border/40 pb-1 text-caption uppercase">
                    <span className="col-span-3">Action</span>
                    <span className="col-span-6">Target / Selector</span>
                    <span className="col-span-3 text-right">Status</span>
                  </div>
                  <div className="grid grid-cols-12 gap-2 py-1 items-center">
                    <span className="col-span-3 font-semibold text-primary">navigate</span>
                    <span className="col-span-6 text-foreground truncate">https://app.studymate.ai</span>
                    <span className="col-span-3 text-right text-primary">done</span>
                  </div>
                  <div className="grid grid-cols-12 gap-2 py-1 items-center">
                    <span className="col-span-3 font-semibold text-primary">click</span>
                    <span className="col-span-6 text-foreground truncate">button#login-submit</span>
                    <span className="col-span-3 text-right text-primary">done</span>
                  </div>
                  <div className="grid grid-cols-12 gap-2 py-1 items-center">
                    <span className="col-span-3 font-semibold text-primary">upload</span>
                    <span className="col-span-6 text-foreground truncate">input[type=&apos;file&apos;]</span>
                    <span className="col-span-3 text-right text-primary">done</span>
                  </div>
                  <div className="grid grid-cols-12 gap-2 py-1 items-center">
                    <span className="col-span-3 font-semibold text-primary">assert</span>
                    <span className="col-span-6 text-foreground truncate">.quiz-container visible</span>
                    <span className="col-span-3 text-right text-primary">passed</span>
                  </div>
                </div>
              )}

              {activeTab === "result" && (
                <div className="rounded-xl border border-border/80 bg-secondary/20 p-5 space-y-3">
                  <div className="flex items-center gap-2 text-primary font-semibold text-body-sm">
                    <MaterialIcon name="check_circle" size={18} />
                    All milestone assertions passed
                  </div>
                  <p className="text-body-sm text-muted-foreground leading-relaxed">
                    Target destination reached without manual intervention. Output integrity confirmed with 0 console errors and 0 unhandled promise rejections.
                  </p>
                  <div className="pt-2 flex items-center gap-3 text-caption font-mono text-muted-foreground">
                    <span>DOM nodes verified: 12</span>
                    <span>•</span>
                    <span>HTTP 200/201 checks: 6</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
