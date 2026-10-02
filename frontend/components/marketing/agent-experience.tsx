"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { AgentActivity, type AgentActivityItem } from "./agent-activity";
import { cn } from "@/lib/utils";

export type ExplorationPhase = "connecting" | "exploring" | "understanding" | "ready";

export interface WorkflowDiscovery {
  id: string;
  label: string;
  description: string;
  icon: string;
}

const defaultDiscoveries: WorkflowDiscovery[] = [
  {
    id: "auth",
    label: "Authentication",
    description: "Sign up, login, and session persistence",
    icon: "lock",
  },
  {
    id: "quiz",
    label: "Quiz generation",
    description: "Create interactive quizzes from study materials",
    icon: "auto_awesome",
  },
  {
    id: "upload",
    label: "Material upload",
    description: "Upload and parse documents and resources",
    icon: "upload_file",
  },
  {
    id: "results",
    label: "Results",
    description: "Review test scores, metrics, and completion state",
    icon: "insights",
  },
];

const initialActivities: AgentActivityItem[] = [
  { id: "1", text: "Connected to your product", status: "running" },
  { id: "2", text: "Exploring navigation", status: "pending" },
  { id: "3", text: "Found sign in and key entry points", status: "pending" },
  { id: "4", text: "Looking for important workflows", status: "pending" },
];

export interface AgentLaunchExperienceProps {
  url: string;
  instruction?: string;
  onReset?: () => void;
  onContinue?: (discoveryId: string) => void;
  className?: string;
}

export function AgentLaunchExperience({
  url,
  instruction,
  onReset,
  onContinue,
  className,
}: AgentLaunchExperienceProps) {
  const router = useRouter();
  const [phase, setPhase] = useState<ExplorationPhase>("connecting");
  const [activities, setActivities] = useState<AgentActivityItem[]>(initialActivities);
  const [selectedWorkflow, setSelectedWorkflow] = useState<string>("auth");

  const displayUrl = url ? url.replace(/^https?:\/\//, "").replace(/\/$/, "") : "your-product.com";

  useEffect(() => {
    if (url && url !== "your-product.com") {
      const params = new URLSearchParams();
      params.set("url", url);
      if (instruction) {
        params.set("intent", instruction);
      }
      router.replace(`/explore?${params.toString()}`);
    }
  }, [url, instruction, router]);

  const handleContinue = () => {
    if (onContinue) {
      onContinue(selectedWorkflow);
    } else {
      router.push(`/explore?url=${encodeURIComponent(url)}&workflow=${encodeURIComponent(selectedWorkflow)}`);
    }
  };

  return (
    <div className={cn("w-full max-w-3xl mx-auto animate-in fade-in zoom-in-95 duration-500", className)}>
      {/* Exploration Header */}
      <div className="mb-8 text-center">
        <span className="text-label text-primary tracking-wider mb-2 inline-block">
          {phase === "ready" ? "Exploration complete" : "Kova is exploring your product"}
        </span>
        <h2 className="text-h2 md:text-h1 text-foreground mb-2">
          {phase === "ready" ? "I found a few things worth testing." : "Observing interface and pathways"}
        </h2>
        <p className="text-mono text-body-sm text-muted-foreground max-w-md mx-auto truncate">
          {url}
          {instruction ? ` — "${instruction}"` : ""}
        </p>
      </div>

      {/* Main Simulation Viewport Frame */}
      <div className="rounded-2xl border border-border bg-card shadow-sm overflow-hidden transition-all duration-300">
        {/* Browser Top Navigation Bar */}
        <div className="flex items-center gap-3 border-b border-border bg-secondary/40 px-4 py-3">
          <div className="flex items-center gap-1.5 shrink-0" aria-hidden="true">
            <span className="h-3 w-3 rounded-full bg-border" />
            <span className="h-3 w-3 rounded-full bg-border" />
            <span className="h-3 w-3 rounded-full bg-border" />
          </div>

          <div className="flex-1 flex items-center justify-center">
            <div className="flex items-center gap-2 rounded-md bg-background px-3 py-1 border border-border/80 max-w-sm w-full">
              <MaterialIcon name="lock" size={13} className="text-muted-foreground shrink-0" />
              <span className="text-mono text-[0.8125rem] text-foreground truncate">
                https://{displayUrl}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            <span
              className={cn(
                "inline-flex items-center gap-1 text-[0.75rem] font-medium px-2 py-0.5 rounded-full",
                phase === "ready"
                  ? "bg-primary/10 text-primary"
                  : "bg-secondary text-muted-foreground"
              )}
            >
              {phase === "ready" ? (
                <>
                  <MaterialIcon name="check" size={12} />
                  Ready
                </>
              ) : (
                <>
                  <MaterialIcon name="progress_activity" size={12} className="animate-spin text-primary" />
                  Live
                </>
              )}
            </span>
          </div>
        </div>

        {/* Viewport Content */}
        <div className="p-6 md:p-8 min-h-[300px]">
          {phase !== "ready" ? (
            <div className="space-y-6">
              {/* Simulated Screen Wireframe with Active Focus Marker */}
              <div className="rounded-xl border border-border/70 bg-background/60 p-5 space-y-4">
                <div className="flex items-center justify-between border-b border-border/50 pb-3">
                  <div className="h-3.5 w-24 rounded bg-muted animate-pulse" />
                  <div className="flex items-center gap-2">
                    <div className="h-3 w-12 rounded bg-muted" />
                    <div className="h-3 w-12 rounded bg-muted" />
                    <div className="h-5 w-16 rounded bg-primary/20 border border-primary/40 flex items-center justify-center">
                      <span className="text-[10px] text-primary font-mono uppercase font-semibold">inspecting</span>
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-3 py-2">
                  <div className="h-16 rounded-lg bg-secondary/60 border border-border/40 p-2.5 space-y-2">
                    <div className="h-2.5 w-3/4 rounded bg-muted" />
                    <div className="h-2 w-1/2 rounded bg-muted/60" />
                  </div>
                  <div className="h-16 rounded-lg bg-secondary/60 border border-border/40 p-2.5 space-y-2">
                    <div className="h-2.5 w-2/3 rounded bg-muted" />
                    <div className="h-2 w-1/3 rounded bg-muted/60" />
                  </div>
                  <div className="h-16 rounded-lg bg-primary/5 border border-primary/30 p-2.5 space-y-2 relative overflow-hidden">
                    <div className="h-2.5 w-4/5 rounded bg-primary/40" />
                    <div className="h-2 w-1/2 rounded bg-primary/20" />
                    <div className="absolute top-2 right-2">
                      <MaterialIcon name="ads_click" size={14} className="text-primary animate-bounce" />
                    </div>
                  </div>
                </div>
              </div>

              {/* Real-time Activity Feed */}
              <div className="pt-2">
                <p className="text-caption text-muted-foreground uppercase tracking-wider mb-3">
                  Agent sequence
                </p>
                <AgentActivity activities={activities} />
              </div>
            </div>
          ) : (
            <div className="animate-in fade-in duration-300 space-y-6">
              <p className="text-body text-muted-foreground">
                Kova discovered key workflows by exploring your product&apos;s interface. Select a journey to run or continue to view execution results.
              </p>

              {/* Discoveries Selection Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                {defaultDiscoveries.map((discovery) => {
                  const isSelected = selectedWorkflow === discovery.id;

                  return (
                    <button
                      key={discovery.id}
                      type="button"
                      onClick={() => setSelectedWorkflow(discovery.id)}
                      className={cn(
                        "flex items-start gap-3.5 p-4 rounded-xl border text-left transition-all duration-200",
                        isSelected
                          ? "border-primary bg-primary/5 ring-1 ring-primary shadow-xs"
                          : "border-border bg-background hover:border-foreground/30 hover:bg-secondary/20"
                      )}
                    >
                      <div
                        className={cn(
                          "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors",
                          isSelected ? "bg-primary text-primary-foreground" : "bg-secondary text-primary"
                        )}
                      >
                        <MaterialIcon name={discovery.icon} size={20} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-1">
                          <p className="text-body-sm font-semibold text-foreground">
                            {discovery.label}
                          </p>
                          {isSelected && (
                            <MaterialIcon name="check" size={16} className="text-primary shrink-0" />
                          )}
                        </div>
                        <p className="text-caption text-muted-foreground mt-0.5 leading-snug">
                          {discovery.description}
                        </p>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        {phase === "ready" && (
          <>
            <Separator />
            <div className="flex items-center justify-between px-6 py-4 bg-secondary/20">
              <Button
                variant="ghost"
                size="sm"
                onClick={onReset}
                className="text-muted-foreground hover:text-foreground"
              >
                <MaterialIcon name="arrow_back" size={16} />
                Start over
              </Button>

              <div className="flex items-center gap-3">
                <Button size="default" onClick={handleContinue} className="px-5 font-medium">
                  Run selected journey
                  <MaterialIcon name="arrow_forward" size={16} />
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Re-export alias for compatibility
export { AgentLaunchExperience as AgentExperience, AgentLaunchExperience as KovaExplorer };
