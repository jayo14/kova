"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button, buttonVariants } from "@/components/ui/button";
import type { Mission, MissionExecution } from "@/lib/types";
import { getExecutionStatusConfig } from "@/lib/utils/execution-status";
import { runMission } from "@/lib/api/missions";
import { cn } from "@/lib/utils";

interface ProjectMissionsProps {
  missions: Mission[];
  executions: Map<string, MissionExecution>;
  projectId: string;
  baseUrl: string;
}

export function ProjectMissions({
  missions,
  executions,
  projectId,
  baseUrl,
}: ProjectMissionsProps) {
  const router = useRouter();
  const [runningId, setRunningId] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [runError, setRunError] = useState<{ id: string; message: string } | null>(null);

  const handleRunMission = (missionId: string) => {
    setRunError(null);
    setRunningId(missionId);
    startTransition(async () => {
      try {
        const exec = await runMission(missionId);
        if (exec?.id) {
          router.push(`/executions/${exec.id}`);
        } else {
          setRunError({ id: missionId, message: "Could not trigger execution. Please try again." });
          setRunningId(null);
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Failed to run mission.";
        setRunError({ id: missionId, message: msg });
        setRunningId(null);
      }
    });
  };
  if (missions.length === 0) {
    return (
      <section
        aria-label="Missions"
        className="rounded-2xl border border-border/80 bg-card/60 p-6 shadow-xs"
      >
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-body-sm font-semibold text-foreground">
            Missions
          </h2>
        </div>
        <p className="text-body-sm text-muted-foreground mb-5 leading-relaxed">
          Kova hasn&apos;t mapped any missions for this product yet.
        </p>
        <Link
          href={`/explore?projectId=${projectId}&url=${encodeURIComponent(baseUrl)}`}
          className={cn(
            buttonVariants({ variant: "outline", size: "sm" }),
            "inline-flex items-center gap-1.5 rounded-xl border-border/80 font-medium hover:bg-secondary/40"
          )}
        >
          <MaterialIcon name="explore" size={16} className="text-primary" />
          <span>Explore product</span>
        </Link>
      </section>
    );
  }

  return (
    <section
      aria-label="Missions"
      className="rounded-2xl border border-border/80 bg-card/60 p-6 shadow-xs"
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-body-sm font-semibold text-foreground">
            Missions
          </h2>
          <p className="text-caption text-muted-foreground mt-0.5">
            Human journeys Kova understands for this product.
          </p>
        </div>
        <span className="inline-flex items-center rounded-full bg-secondary/60 px-2.5 py-0.5 text-caption font-medium text-muted-foreground">
          {missions.length}
        </span>
      </div>

      <div className="divide-y divide-border/60">
        {missions.map((mission) => {
          const lastExec = executions.get(mission.id);
          const statusConfig = lastExec ? getExecutionStatusConfig(lastExec.status) : null;
          const stepCount = mission.steps?.length ?? 0;

          return (
            <div
              key={mission.id}
              className="py-3.5 first:pt-0 last:pb-0"
            >
              <div className="group flex flex-col sm:flex-row sm:items-center justify-between gap-3 transition-colors">
                <div className="min-w-0 flex-1">
                  <Link
                    href={`/flows/${mission.id}`}
                    className="text-body-sm font-medium text-foreground hover:text-primary transition-colors block truncate"
                  >
                    {mission.name}
                  </Link>

                  <div className="flex flex-wrap items-center gap-2 mt-1.5">
                    {mission.persona && (
                      <span className="inline-flex items-center gap-1 rounded-md border border-border/70 bg-secondary/30 px-2 py-0.5 text-caption text-muted-foreground">
                        <MaterialIcon name="person" size={12} className="opacity-70" />
                        <span>{mission.persona}</span>
                      </span>
                    )}
                    <span className="text-caption text-muted-foreground">
                      {stepCount} {stepCount === 1 ? "step" : "steps"}
                    </span>
                    {statusConfig ? (
                      <>
                        <span className="text-border" aria-hidden="true">·</span>
                        <span
                          className={cn(
                            "inline-flex items-center gap-1 text-caption font-medium px-2 py-0.5 rounded-md",
                            statusConfig.badgeClass
                          )}
                        >
                          <span
                            className={cn(
                              "h-1.5 w-1.5 rounded-full",
                              statusConfig.dotClass,
                              statusConfig.isAnimated && "animate-pulse"
                            )}
                          />
                          <span>{statusConfig.label}</span>
                        </span>
                      </>
                    ) : (
                      <>
                        <span className="text-border" aria-hidden="true">·</span>
                        <span className="text-caption text-muted-foreground">
                          Not yet run
                        </span>
                      </>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0 self-end sm:self-center">
                  <Link
                    href={`/flows/${mission.id}`}
                    className={cn(
                      buttonVariants({ variant: "ghost", size: "sm" }),
                      "h-8 gap-1 rounded-lg px-2.5 text-body-xs font-medium text-muted-foreground hover:text-foreground hover:bg-secondary/60"
                    )}
                    title="View mission details"
                  >
                    <MaterialIcon name="visibility" size={14} />
                    <span className="hidden sm:inline">Details</span>
                  </Link>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleRunMission(mission.id)}
                    disabled={runningId === mission.id || mission.active === false}
                    className="h-8 gap-1 rounded-lg px-2.5 text-body-xs font-medium text-primary hover:text-primary hover:bg-primary/10 border-primary/20"
                    title={mission.active === false ? "Mission must be activated to run" : "Run mission now"}
                  >
                    {runningId === mission.id ? (
                      <MaterialIcon name="progress_activity" size={14} className="animate-spin text-primary" />
                    ) : (
                      <MaterialIcon name="play_arrow" size={14} className="text-primary" />
                    )}
                    <span>{runningId === mission.id ? "Running..." : "Run"}</span>
                  </Button>
                </div>
              </div>
              {runError?.id === mission.id && (
                <p className="text-caption text-destructive px-1 pt-1.5">
                  {runError.message}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
