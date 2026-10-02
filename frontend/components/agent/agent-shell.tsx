"use client";

import type { ReactNode } from "react";
import { Logo } from "@/components/shared/logo";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import type { ExploreState } from "@/lib/types";
import { cn } from "@/lib/utils";

interface AgentShellProps {
  url: string;
  state: ExploreState;
  projectName?: string;
  onStop?: () => void;
  onBack?: () => void;
  children: ReactNode;
}

const stateLabels: Partial<Record<ExploreState, string>> = {
  connecting: "Connecting",
  loading: "Loading page",
  validating_page: "Validating page",
  exploring: "Exploring",
  understanding: "Understanding",
  auth_required: "Needs your input",
  authenticating: "Signing in",
  asking: "Needs your input",
  discovering: "Discovering",
  planning: "Planning",
  ready: "Ready",
  executing: "Executing mission",
  completed: "Completed",
  mission_selected: "Preparing mission",
  mission_created: "Preparing mission",
  failed: "Failed",
  cancelled: "Stopped",
};

export function AgentShell({
  url,
  state,
  projectName,
  onStop,
  onBack,
  children,
}: AgentShellProps) {
  const isRunning = [
    "connecting",
    "loading",
    "validating_page",
    "exploring",
    "understanding",
    "authenticating",
    "discovering",
    "planning",
    "asking",
    "executing",
  ].includes(state);

  const hostname = (() => {
    if (!url) return null;
    try {
      return new URL(url).hostname;
    } catch {
      return url.replace(/^https?:\/\//, "").split("/")[0] || null;
    }
  })();

  const displayName = projectName || hostname;

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="sticky top-0 z-50 flex h-14 items-center justify-between border-b border-border bg-background/80 px-4 md:px-6 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          {onBack && (
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={onBack}
              className="text-muted-foreground hover:text-foreground"
              aria-label="Back to previous screen"
            >
              <MaterialIcon name="arrow_back" size={16} />
            </Button>
          )}
          {onBack && <Separator orientation="vertical" className="h-4" />}
          <Logo size="sm" />

          {displayName && state !== "idle" && (
            <>
              <span className="text-muted-foreground/40 select-none">/</span>
              <div className="flex items-center gap-2">
                <span className="text-body-sm font-medium text-foreground truncate max-w-[180px] sm:max-w-[280px]">
                  {displayName}
                </span>
              </div>
            </>
          )}
        </div>

        <div className="flex items-center gap-3">
          {state !== "idle" && (
            <div className="hidden sm:inline-flex items-center gap-2 rounded-full border border-border bg-secondary/30 px-3 py-1 text-caption text-muted-foreground">
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  state === "ready"
                    ? "bg-emerald-600"
                    : state === "failed"
                      ? "bg-destructive"
                      : state === "cancelled"
                        ? "bg-muted-foreground"
                        : "bg-primary animate-pulse"
                )}
              />
              <span>{stateLabels[state] || state}</span>
            </div>
          )}

          {isRunning && onStop && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onStop}
              className="text-muted-foreground hover:text-foreground border border-border/60 hover:bg-secondary/40"
              aria-label="Stop exploration"
            >
              <MaterialIcon name="stop" size={14} />
              Stop
            </Button>
          )}
        </div>
      </header>

      <main className="flex flex-1 flex-col overflow-hidden">
        {children}
      </main>
    </div>
  );
}
