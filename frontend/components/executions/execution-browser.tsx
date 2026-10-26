"use client";

import { useState, useEffect, useMemo } from "react";
import type { ExecutionStatus } from "@/lib/types";
import { MaterialIcon } from "@/components/shared/material-icon";
import { getExecutionStatusConfig } from "@/lib/utils/execution-status";
import { cn } from "@/lib/utils";
import { LiveViewport } from "@/components/agent/live-viewport";

export interface StepScreenshot {
  url: string;
  title: string;
  stepIndex: number | null;
  status?: string | null;
}

export interface ExecutionBrowserProps {
  url: string;
  status: ExecutionStatus;
  className?: string;
  errorMessage?: string | null;
  latestScreenshot?: string | null;
  currentAction?: string | null;
  events?: Array<{ eventType: string; payload?: Record<string, unknown> }>;
  executionId?: string;
  stepScreenshots?: StepScreenshot[];
}

const activeStatuses: ExecutionStatus[] = [
  "created",
  "queued",
  "initializing",
  "browser_ready",
  "running",
  "waiting",
  "paused",
  "human_controlled",
  "resuming",
];

const agentControlledStatuses: ExecutionStatus[] = [
  "running",
  "initializing",
  "browser_ready",
  "paused",
  "human_controlled",
  "resuming",
];

export function ExecutionBrowser({
  url,
  status,
  className,
  errorMessage,
  latestScreenshot,
  currentAction,
  events = [],
  executionId,
  stepScreenshots = [],
}: ExecutionBrowserProps) {
  const [liveUrl, setLiveUrl] = useState<string>(url);
  const [actionFlash, setActionFlash] = useState<string | null>(null);
  const [scrubber, setScrubber] = useState<{ count: number; index: number | null }>({
    count: stepScreenshots.length,
    index: null,
  });

  // A new set of screenshots resets the selection without an extra render pass.
  const scrubberIndex = scrubber.count === stepScreenshots.length ? scrubber.index : null;

  const selectedShot = useMemo(() => {
    if (stepScreenshots.length === 0) return null;
    if (scrubberIndex === null) return stepScreenshots[stepScreenshots.length - 1];
    return stepScreenshots[scrubberIndex] ?? stepScreenshots[stepScreenshots.length - 1];
  }, [stepScreenshots, scrubberIndex]);

  const displayScreenshot = selectedShot?.url ?? latestScreenshot;

  const isActive = activeStatuses.includes(status);
  const isAgentControlled = agentControlledStatuses.includes(status);
  const statusConfig = getExecutionStatusConfig(status);

  useEffect(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const p = events[i]?.payload;
      if (p && typeof p.url === "string" && p.url) {
        setLiveUrl(p.url);
        break;
      }
    }
  }, [events]);

  useEffect(() => {
    if (currentAction) {
      setActionFlash(currentAction);
      const t = setTimeout(() => setActionFlash(null), 2000);
      return () => clearTimeout(t);
    }
  }, [currentAction]);

  useEffect(() => {
    if (!events.some((e) => e.payload && typeof (e.payload as Record<string, unknown>).url === "string")) {
      setLiveUrl(url);
    }
  }, [url, events]);

  const displayHost = (() => {
    try {
      return new URL(liveUrl.startsWith("http") ? liveUrl : `https://${liveUrl}`).hostname;
    } catch {
      return liveUrl.replace(/^https?:\/\//, "").split("/")[0] || "product.com";
    }
  })();

  const displayPath = (() => {
    try {
      const u = new URL(liveUrl.startsWith("http") ? liveUrl : `https://${liveUrl}`);
      return u.pathname + u.search;
    } catch {
      return "/";
    }
  })();

  return (
    <div
      role="region"
      aria-label="Browser workspace viewport"
      className={cn(
        "flex flex-col rounded-2xl border bg-card overflow-hidden shadow-xs transition-all",
        isAgentControlled ? "border-primary/40 shadow-primary/5" : "border-border/80",
        className
      )}
    >
      {/* Browser Chrome Header */}
      <div className="flex items-center justify-between border-b border-border/70 bg-secondary/30 px-4 py-2.5">
        {/* Window Controls */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5" aria-hidden="true">
            <span className="h-2.5 w-2.5 rounded-full bg-border/90" />
            <span className="h-2.5 w-2.5 rounded-full bg-border/90" />
            <span className="h-2.5 w-2.5 rounded-full bg-border/90" />
          </div>
        </div>

        {/* Address Bar */}
        <div className="flex max-w-xs sm:max-w-sm md:max-w-md items-center gap-1.5 rounded-lg border border-border/60 bg-background/80 px-3 py-1 text-caption font-mono text-muted-foreground">
          <MaterialIcon
            name="lock"
            size={12}
            className="text-emerald-600 shrink-0"
          />
          <span className="truncate text-foreground font-medium">{displayHost}</span>
          <span className="truncate text-muted-foreground">{displayPath}</span>
        </div>

        {/* Status & Controls */}
        <div className="flex items-center gap-2">
          {isActive ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/25 bg-primary/10 px-2.5 py-0.5 text-caption font-medium text-primary">
              <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
              <span className="hidden sm:inline">Live</span>
            </span>
          ) : (
            <div className="inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-secondary/40 px-2.5 py-0.5 text-caption text-foreground">
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  statusConfig.dotClass,
                  statusConfig.isAnimated && "animate-pulse"
                )}
              />
              <span className="hidden sm:inline">{statusConfig.label}</span>
            </div>
          )}
        </div>
      </div>

      {/* Viewport Workspace */}
      <div className="relative flex-1 min-h-[420px] sm:min-h-[520px] md:min-h-[560px] bg-background/50 overflow-hidden select-none">
        {/* Agent Control Glow */}
        {isAgentControlled && (
          <div className="absolute inset-0 z-10 pointer-events-none">
            <div className="absolute inset-0 rounded-none border-2 border-primary/20 animate-pulse" />
            <div className="absolute top-2 left-2 w-8 h-8 border-t-2 border-l-2 border-primary/40 rounded-tl-lg" />
            <div className="absolute top-2 right-2 w-8 h-8 border-t-2 border-r-2 border-primary/40 rounded-tr-lg" />
            <div className="absolute bottom-2 left-2 w-8 h-8 border-b-2 border-l-2 border-primary/40 rounded-bl-lg" />
            <div className="absolute bottom-2 right-2 w-8 h-8 border-b-2 border-r-2 border-primary/40 rounded-br-lg" />
          </div>
        )}

        {/* Action flash label */}
        {actionFlash && isActive && (
          <div className="absolute top-14 left-1/2 -translate-x-1/2 z-30 pointer-events-none animate-in fade-in slide-in-from-top-1 duration-200">
            <div className="rounded-full bg-primary/90 text-primary-foreground px-3 py-1 text-[11px] font-mono shadow-md">
              {actionFlash}
            </div>
          </div>
        )}

        {/* Live Viewport (active execution browser) */}
        {executionId && isActive ? (
          <div className="absolute inset-0 w-full h-full z-20">
            <LiveViewport
              executionId={executionId}
              fallbackScreenshot={latestScreenshot}
              hideHeader={true}
              className="w-full h-full rounded-none border-0 bg-transparent"
            />
          </div>
        ) : (
          /* Static screenshot fallback / final snapshot */
          <div className="absolute inset-0 w-full h-full z-20 flex items-center justify-center bg-black/5 dark:bg-black/30 overflow-hidden">
            {displayScreenshot ? (
              <div className="relative w-full h-full flex items-center justify-center">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  key={displayScreenshot}
                  src={displayScreenshot}
                  alt="Browser snapshot"
                  className="w-full h-full object-contain animate-in fade-in duration-200 select-none"
                />
              </div>
            ) : isActive ? (
              <div className="flex flex-col items-center text-center p-6 max-w-md animate-in fade-in duration-300">
                <div className="relative mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-2xl bg-primary opacity-20" />
                  <MaterialIcon name="smart_toy" size={32} className="text-primary animate-pulse" />
                </div>
                <h3 className="text-body-md font-semibold text-foreground mb-1.5">
                  Starting browser...
                </h3>
                <p className="text-body-xs text-muted-foreground mb-4">
                  {currentAction || `Launching Chromium on ${displayHost}...`}
                </p>
              </div>
            ) : (
              <div className="flex flex-col items-center text-center p-6 max-w-md animate-in fade-in duration-300">
                <div className="relative mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-border bg-secondary/50">
                  <MaterialIcon
                    name={status === "completed" ? "check_circle" : status === "blocked" ? "shield" : "browser_updated"}
                    size={32}
                    className="text-muted-foreground"
                  />
                </div>
                <h3 className="text-body-md font-semibold text-foreground mb-1.5">
                  {status === "completed"
                    ? "Execution completed"
                    : status === "blocked"
                    ? "Execution blocked"
                    : "Execution finished"}
                </h3>
                <p className="text-body-xs text-muted-foreground mb-4">
                  {errorMessage || `Browser session ended for ${displayHost}.`}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Active interaction banner */}
        {isActive && (
          <div className="absolute top-3 left-1/2 -translate-x-1/2 z-30 pointer-events-none animate-in fade-in slide-in-from-top-2 duration-300">
            <div className="flex items-center gap-2.5 rounded-full border border-primary/30 bg-background/95 px-4 py-1.5 text-caption font-medium text-foreground shadow-md backdrop-blur-sm">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
              </span>
              <span className="text-body-xs font-semibold text-primary">Kova interacting:</span>
              <span className="text-body-xs text-foreground truncate max-w-xs sm:max-w-md">
                {currentAction || "Operating browser..."}
              </span>
            </div>
          </div>
        )}

        {/* Terminal Completed */}
        {!isActive && status === "completed" && (
          <div className="absolute bottom-4 left-4 right-4 z-30 flex items-center justify-between rounded-xl border border-emerald-500/30 bg-card/95 backdrop-blur-md p-3.5 shadow-lg animate-in fade-in slide-in-from-bottom-3 duration-300">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 shrink-0">
                <MaterialIcon name="check_circle" size={18} />
              </div>
              <div>
                <p className="text-body-sm font-semibold text-foreground">Mission completed</p>
                <p className="text-caption text-muted-foreground">
                  Kova successfully accomplished this mission and verified the outcome.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Terminal Blocked */}
        {!isActive && status === "blocked" && (
          <div className="absolute bottom-4 left-4 right-4 z-30 flex items-center justify-between rounded-xl border border-amber-500/30 bg-card/95 backdrop-blur-md p-3.5 shadow-lg animate-in fade-in slide-in-from-bottom-3 duration-300">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400 shrink-0">
                <MaterialIcon name="shield" size={18} />
              </div>
              <div>
                <p className="text-body-sm font-semibold text-foreground">
                  Execution blocked
                </p>
                <p className="text-caption text-muted-foreground line-clamp-1">
                  {errorMessage || "Verification blocked: human action or valid test account required."}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Terminal Failed / Error / Timeout / Cancelled */}
        {!isActive && (status === "failed" || status === "timeout" || status === "error" || status === "cancelled" || status === "unverified") && (
          <div className="absolute bottom-4 left-4 right-4 z-30 flex items-center justify-between rounded-xl border border-destructive/30 bg-card/95 backdrop-blur-md p-3.5 shadow-lg animate-in fade-in slide-in-from-bottom-3 duration-300">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-destructive/10 text-destructive shrink-0">
                <MaterialIcon name={status === "timeout" ? "timer_off" : status === "cancelled" ? "cancel" : "error"} size={18} />
              </div>
              <div>
                <p className="text-body-sm font-semibold text-foreground">
                  {status === "timeout" ? "Execution timed out" : status === "cancelled" ? "Execution cancelled" : "Execution failed"}
                </p>
                <p className="text-caption text-muted-foreground line-clamp-1">
                  {errorMessage || "Kova could not accomplish the mission objective."}
                </p>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Step scrubber — replay each verified step without leaving the page */}
      {!isActive && stepScreenshots.length > 0 && (
        <div className="border-t border-border/70 bg-secondary/20 px-3 py-2.5">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="flex items-center gap-1.5 text-caption font-medium text-foreground">
              <MaterialIcon name="history" size={14} className="text-muted-foreground" />
              <span>Verified steps</span>
            </div>
            <span className="text-caption text-muted-foreground">
              {selectedShot ? `${(scrubberIndex ?? stepScreenshots.length - 1) + 1} of ${stepScreenshots.length}` : ""}
            </span>
          </div>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {stepScreenshots.map((shot, index) => {
              const active = (scrubberIndex ?? stepScreenshots.length - 1) === index;
              const upperStatus = shot.status ? String(shot.status).toUpperCase() : null;
              const dotClass = !upperStatus
                ? null
                : upperStatus === "VERIFIED"
                ? "bg-emerald-500"
                : upperStatus === "FAILED"
                ? "bg-destructive"
                : "bg-muted-foreground/70";
              return (
                <button
                  key={`${shot.url}-${index}`}
                  type="button"
                  onClick={() => setScrubber({ count: stepScreenshots.length, index })}
                  aria-pressed={active}
                  aria-label={`Show ${shot.title || `step ${index + 1}`}`}
                  className={cn(
                    "relative h-16 w-28 shrink-0 overflow-hidden rounded-md border-2 bg-background transition-colors",
                    active ? "border-primary" : "border-border/60 hover:border-border"
                  )}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={shot.url} alt="" className="h-full w-full object-cover" />
                  {dotClass && (
                    <span
                      aria-hidden="true"
                      className="absolute top-1 right-1 z-10 h-2 w-2 rounded-full ring-1 ring-white/40 shadow-sm"
                    >
                      <span className={cn("block h-full w-full rounded-full", dotClass)} />
                    </span>
                  )}
                  <span className="absolute bottom-0 left-0 right-0 bg-black/60 px-1 py-0.5 text-[10px] font-medium text-white">
                    {shot.stepIndex != null ? `Step ${shot.stepIndex + 1}` : `Shot ${index + 1}`}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
