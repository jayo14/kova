"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { Mission, MissionExecution } from "@/lib/types";
import { updateMission } from "@/lib/api/missions";
import { MaterialIcon } from "@/components/shared/material-icon";
import { MissionDetailHeader } from "./mission-detail-header";
import { MissionJourney } from "./mission-journey";
import { MissionExecutionHistory } from "./mission-execution-history";

interface MissionDetailProps {
  mission: Mission;
  executions: MissionExecution[];
  onMissionUpdated?: (updated: Mission) => void;
}

function formatSuccessCondition(
  cond: Record<string, unknown> | null
): string {
  if (!cond) return "Outcome verified against browser state";
  const keys = Object.keys(cond);
  if (keys.includes("auth_verified")) return "Authentication reaches the post-login state";
  if (keys.includes("text_visible")) return `Page shows "${String(cond.text_visible)}"`;
  if (keys.includes("element_visible")) return "Expected element is visible on the page";
  if (keys.includes("element_absent")) return "Interfering element is no longer present";
  if (keys.includes("element_count")) return "Expected number of results are present";
  if (keys.includes("heading_changed")) return "Page heading changes to the target content";
  if (keys.includes("url_matches")) return "Browser lands on the expected page";
  if (keys.includes("url_changed_to")) return "Browser navigates to the target page";
  if (keys.includes("url_changed_from")) return "Browser leaves the starting page";
  return keys.length > 0 ? `Verified via: ${keys.join(", ")}` : "Outcome verified against browser state";
}

export function MissionDetail({
  mission: initialMission,
  executions,
  onMissionUpdated,
}: MissionDetailProps) {
  const router = useRouter();
  const [mission, setMission] = useState<Mission>(initialMission);
  const [command, setCommand] = useState("");
  const [isUpdating, startUpdateTransition] = useTransition();
  const [feedback, setFeedback] = useState<string | null>(null);

  const commandSuggestions = [
    "Use an administrator instead.",
    "Also verify the results page.",
    "Don't create a new account.",
  ];

  const handleCommandSubmit = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;

    startUpdateTransition(async () => {
      const updated = await updateMission(mission.id, {
        description: trimmed,
      });

      if (updated) {
        setMission(updated);
        onMissionUpdated?.(updated);
        setFeedback("Mission updated with new instructions.");
        setCommand("");
        router.refresh();
      } else {
        setFeedback("Failed to update mission.");
      }

      setTimeout(() => setFeedback(null), 4000);
    });
  };

  return (
    <div className="w-full max-w-4xl mx-auto space-y-8">
      {/* Header with Navigation and Actions */}
      <MissionDetailHeader
        mission={mission}
        onMissionUpdated={(updated) => {
          setMission(updated);
          onMissionUpdated?.(updated);
        }}
      />

      {/* Command Surface: Change this mission */}
      <section
        aria-label="Mission command input"
        className="rounded-2xl border border-border/80 bg-card/60 p-5 shadow-xs"
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleCommandSubmit(command);
          }}
          className="space-y-3"
        >
          <div className="flex items-center justify-between">
            <label
              htmlFor="mission-command-input"
              className="text-body-xs font-semibold uppercase tracking-wider text-muted-foreground"
            >
              Change this mission
            </label>
            {feedback && (
              <span className="text-body-xs text-primary font-medium">
                {feedback}
              </span>
            )}
          </div>

          <div className="relative flex items-center">
            <input
              id="mission-command-input"
              type="text"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder='e.g. "Use an administrator instead" or "Also verify the results page"'
              disabled={isUpdating}
              className="w-full rounded-xl border border-border/80 bg-background/80 py-2.5 pl-3.5 pr-10 text-body-sm text-foreground placeholder:text-muted-foreground/60 outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition-colors disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!command.trim() || isUpdating}
              className="absolute right-2 flex h-7 w-7 items-center justify-center rounded-lg bg-primary text-primary-foreground disabled:opacity-30 transition-opacity"
              aria-label="Apply adjustment"
            >
              {isUpdating ? (
                <MaterialIcon
                  name="progress_activity"
                  size={14}
                  className="animate-spin"
                />
              ) : (
                <MaterialIcon name="arrow_forward" size={14} />
              )}
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <span className="text-caption text-muted-foreground/70">Suggestions:</span>
            {commandSuggestions.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => handleCommandSubmit(suggestion)}
                className="rounded-lg border border-border/70 bg-secondary/30 px-2 py-0.5 text-caption text-muted-foreground hover:bg-secondary/70 hover:text-foreground transition-colors"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </form>
      </section>

      {/* Main Content Details */}
      <div className="grid gap-8 lg:grid-cols-3">
        {/* Left 2 Columns: Objective, Persona, Success Condition, Journey */}
        <div className="space-y-8 lg:col-span-2">
          {/* Objective */}
          <section aria-label="Objective" className="space-y-2">
            <h2 className="text-body-sm font-semibold uppercase tracking-wider text-caption text-muted-foreground">
              Objective
            </h2>
            <p className="text-body text-foreground/90 leading-relaxed">
              {mission.objective || mission.description || "No specific objective detailed."}
            </p>
          </section>

          {/* Persona */}
          {mission.persona && (
            <section aria-label="Persona" className="space-y-2">
              <h2 className="text-body-sm font-semibold uppercase tracking-wider text-caption text-muted-foreground">
                Persona
              </h2>
              <div className="inline-flex items-center gap-1.5 rounded-lg border border-border/80 bg-secondary/30 px-3 py-1.5 text-body-sm font-medium text-foreground">
                <MaterialIcon name="person" size={16} className="text-primary/70" />
                <span>{mission.persona}</span>
              </div>
            </section>
          )}

          {/* Success Condition */}
          {mission.successCondition && (
            <section aria-label="Success condition" className="space-y-2">
              <h2 className="text-body-sm font-semibold uppercase tracking-wider text-caption text-muted-foreground">
                Success condition
              </h2>
              <div className="flex items-start gap-2.5 rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3.5">
                <MaterialIcon
                  name="check_circle"
                  size={18}
                  className="shrink-0 mt-0.5 text-emerald-600 dark:text-emerald-400"
                />
                <div>
                  <p className="text-body-sm font-medium text-foreground">
                    {formatSuccessCondition(mission.successCondition)}
                  </p>
                  <p className="text-caption text-muted-foreground mt-0.5">
                    How Kova verifies the mission succeeded.
                  </p>
                </div>
              </div>
            </section>
          )}

          {/* Journey Stages */}
          <div className="border-t border-border/60 pt-6">
            <MissionJourney steps={mission.steps} />
          </div>
        </div>

        {/* Right Column: Execution History */}
        <div className="border-t border-border/60 pt-6 lg:border-t-0 lg:border-l lg:border-border/60 lg:pl-8 lg:pt-0">
          <MissionExecutionHistory
            executions={executions}
            missionName={mission.name}
          />
        </div>
      </div>
    </div>
  );
}
