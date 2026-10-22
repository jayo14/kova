"use client";

import { useState, useEffect, type ReactNode } from "react";
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
  onProjectNameChange?: (newName: string) => void;
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
  onProjectNameChange,
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
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editTitleValue, setEditTitleValue] = useState(displayName || "");

  useEffect(() => {
    if (!isEditingTitle) {
      setEditTitleValue(displayName || "");
    }
  }, [displayName, isEditingTitle]);

  const handleTitleCommit = () => {
    const trimmed = editTitleValue.trim();
    if (trimmed && trimmed !== displayName) {
      onProjectNameChange?.(trimmed);
    } else {
      setEditTitleValue(displayName || "");
    }
    setIsEditingTitle(false);
  };

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
                {isEditingTitle ? (
                  <input
                    type="text"
                    value={editTitleValue}
                    autoFocus
                    onChange={(e) => setEditTitleValue(e.target.value)}
                    onBlur={handleTitleCommit}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        handleTitleCommit();
                      } else if (e.key === "Escape") {
                        setEditTitleValue(displayName || "");
                        setIsEditingTitle(false);
                      }
                    }}
                    className="h-7 rounded border border-primary bg-background px-2 font-body text-body-sm font-medium text-foreground outline-none ring-1 ring-primary/40 focus:border-primary max-w-[200px] sm:max-w-[280px]"
                    aria-label="Edit product title"
                  />
                ) : (
                  <span
                    onDoubleClick={() => {
                      setEditTitleValue(displayName || "");
                      setIsEditingTitle(true);
                    }}
                    title="Double click to edit product title"
                    className="text-body-sm font-medium text-foreground truncate max-w-[180px] sm:max-w-[280px] cursor-pointer hover:bg-secondary/70 rounded px-1.5 py-0.5 -mx-1.5 transition-colors select-none"
                  >
                    {displayName}
                  </span>
                )}
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
