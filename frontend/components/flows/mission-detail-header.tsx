"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Mission } from "@/lib/types";
import { runMission, deleteMission, updateMission } from "@/lib/api/missions";
import { getErrorMessage } from "@/lib/api/errors";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { ModeBadge } from "@/components/shared/mode-badge";
import { Button } from "@/components/ui/button";
import { AdjustMissionDialog } from "./adjust-mission-dialog";

interface MissionDetailHeaderProps {
  mission: Mission;
  onMissionUpdated?: (updated: Mission) => void;
}

function formatUrl(url: string): string {
  try {
    return new URL(url.startsWith("http") ? url : `https://${url}`).hostname;
  } catch {
    return url;
  }
}

export function MissionDetailHeader({
  mission,
  onMissionUpdated,
}: MissionDetailHeaderProps) {
  const router = useRouter();
  const [isRunning, startRunTransition] = useTransition();
  const [adjustOpen, setAdjustOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRun = () => {
    setError(null);
    startRunTransition(async () => {
      try {
        if (mission.active === false) {
          try {
            await updateMission(mission.id, { active: true } as any);
          } catch {
            // Ignore non-fatal update error
          }
        }
        const exec = await runMission(mission.id);
        if (exec) {
          router.push(`/executions/${exec.id}`);
        } else {
          setError("Failed to start mission execution. Please try again.");
        }
      } catch (error) {
        setError(getErrorMessage(error, "Failed to start mission execution."));
      }
    });
  };

  const handleAdjustSave = async (
    missionId: string,
    instruction: string,
    updatedFields?: Partial<Mission>
  ) => {
    const patch = {
      description: instruction,
      ...(updatedFields?.name && { name: updatedFields.name }),
      ...(updatedFields?.persona && { persona: updatedFields.persona }),
      ...(updatedFields?.objective && { objective: updatedFields.objective }),
      // successCondition is structured; only forward it if explicitly provided.
      ...(updatedFields?.successCondition && {
        successCondition: updatedFields.successCondition,
      }),
    };

    const updated = await updateMission(missionId, patch);
    if (updated && onMissionUpdated) {
      onMissionUpdated(updated);
    }
    router.refresh();
  };

  const handleDelete = async () => {
    if (!confirm(`Are you sure you want to delete "${mission.name}"?`)) return;
    const success = await deleteMission(mission.id);
    if (success) {
      router.push("/flows");
      router.refresh();
    } else {
      setError("Failed to delete mission.");
    }
  };

  return (
    <div className="mb-8 space-y-4">
      {/* Breadcrumb / Back Link */}
      <Breadcrumbs parentHref="/flows" parentLabel="Flows" currentLabel={mission.name} />

      {error && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-xl bg-destructive/10 px-3.5 py-2.5 text-body-sm text-destructive"
        >
          <MaterialIcon name="error" size={16} />
          <span>{error}</span>
        </div>
      )}

      {mission.stale_reason && (
        <div
          role="note"
          className="flex items-center gap-2 rounded-xl bg-amber-500/10 border border-amber-500/20 px-3.5 py-2.5 text-body-sm text-amber-500"
        >
          <MaterialIcon name="warning" size={16} />
          <span><strong>Stale reason:</strong> {mission.stale_reason}</span>
        </div>
      )}

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-display sm:text-[2.25rem] font-bold text-foreground mb-1.5 tracking-tight truncate">
            {mission.name}
          </h1>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-body-sm text-muted-foreground">
            <ModeBadge mode={mission.mode} />
            {(mission.stale_reason || mission.status === "stale") && (
              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-amber-500/10 text-amber-500 border border-amber-500/20">
                Stale
              </span>
            )}
            {mission.requires_review && (
              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-rose-500/10 text-rose-500 border border-rose-500/20">
                Requires review
              </span>
            )}
            <span aria-hidden="true">·</span>

            <Link
              href={`/projects/${mission.projectId}`}
              className="font-medium text-foreground hover:text-primary transition-colors underline-offset-4 hover:underline"
            >
              {mission.projectName}
            </Link>
            {mission.projectUrl && (
              <>
                <span aria-hidden="true">·</span>
                <a
                  href={
                    mission.projectUrl.startsWith("http")
                      ? mission.projectUrl
                      : `https://${mission.projectUrl}`
                  }
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 hover:text-foreground transition-colors"
                >
                  <span>{formatUrl(mission.projectUrl)}</span>
                  <MaterialIcon name="open_in_new" size={13} className="opacity-70" />
                </a>
              </>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setAdjustOpen(true)}
            className="gap-1.5 rounded-xl border-border/80 text-foreground hover:bg-secondary/40"
          >
            <MaterialIcon name="edit" size={16} className="text-muted-foreground" />
            <span>Adjust</span>
          </Button>

          <Button
            onClick={handleRun}
            disabled={isRunning}
            size="sm"
            title="Run mission"
            className="gap-1.5 rounded-xl font-medium shadow-sm"
          >
            {isRunning ? (
              <MaterialIcon
                name="progress_activity"
                size={16}
                className="animate-spin"
              />
            ) : (
              <MaterialIcon name="play_arrow" size={16} />
            )}
            <span>{isRunning ? "Starting..." : "Run mission"}</span>
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={handleDelete}
            title="Delete mission"
            className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
          >
            <MaterialIcon name="delete" size={16} />
          </Button>
        </div>
      </div>

      <AdjustMissionDialog
        mission={mission}
        open={adjustOpen}
        onOpenChange={setAdjustOpen}
        onSave={handleAdjustSave}
      />
    </div>
  );
}
