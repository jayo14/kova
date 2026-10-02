"use client";

import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import type { SuggestedMission } from "@/lib/types";
import { cn } from "@/lib/utils";

interface MissionCardProps {
  mission: SuggestedMission;
  selected: boolean;
  onSelect: (id: string) => void;
  onRun: (id: string) => void;
  onEdit: (mission: SuggestedMission) => void;
}

function formatSuccessCondition(raw: Record<string, unknown>): string {
  if (keys(raw).includes("auth_verified")) return "Authentication verified";
  if (keys(raw).includes("url_changed_from")) return "URL changed from login page";
  if (keys(raw).includes("element_visible")) return "Element visible on page";
  if (keys(raw).includes("element_absent")) return "Element no longer visible";
  if (keys(raw).includes("element_count")) return "Expected results present";
  if (keys(raw).includes("text_visible")) return `Shows "${String(raw.text_visible)}"`;
  if (keys(raw).includes("url_matches")) return "Lands on expected page";
  const k = keys(raw);
  return k.length > 0 ? k[0] : "Verified";
}

function keys(obj: Record<string, unknown>): string[] {
  return Object.keys(obj);
}

export function MissionCard({
  mission,
  selected,
  onSelect,
  onRun,
  onEdit,
}: MissionCardProps) {
  return (
    <div
      className={cn(
        "group relative rounded-2xl border bg-card p-5 transition-all duration-200 cursor-pointer shadow-xs",
        selected
          ? "border-primary ring-2 ring-primary/15 bg-primary/[0.02]"
          : "border-border hover:border-muted-foreground/30 hover:bg-secondary/15"
      )}
      onClick={() => onSelect(mission.id)}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(mission.id);
        }
      }}
    >
      <div className="flex items-start justify-between gap-4">
        {/* Checkbox and Mission Content */}
        <div className="flex items-start gap-3 flex-1 min-w-0">
          <div
            className={cn(
              "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors",
              selected
                ? "border-primary bg-primary text-primary-foreground"
                : "border-muted-foreground/40 group-hover:border-foreground/60"
            )}
            aria-hidden="true"
          >
            {selected && <MaterialIcon name="check" size={14} className="font-bold" />}
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <h3 className="text-body font-semibold text-foreground">
                {mission.title}
              </h3>
              {mission.recommended && (
                <span className="rounded-full bg-primary/10 border border-primary/20 px-2 py-0.5 text-[10px] font-medium text-primary">
                  Recommended
                </span>
              )}
              {mission.category && (
                <span className={cn(
                  "rounded-full px-2 py-0.5 text-[10px] font-medium border",
                  mission.category === "auth" && "bg-amber-500/10 border-amber-500/20 text-amber-600",
                  mission.category === "feature" && "bg-blue-500/10 border-blue-500/20 text-blue-600",
                  mission.category === "content" && "bg-green-500/10 border-green-500/20 text-green-600",
                  mission.category === "navigation" && "bg-gray-500/10 border-gray-500/20 text-gray-600",
                )}>
                  {mission.category}
                </span>
              )}
            </div>

            {/* Journey Steps — the meaningful user path */}
            {mission.journey && mission.journey.length > 0 && (
              <div className="mb-2.5 flex flex-col gap-1">
                {mission.journey.map((step, i) => (
                  <div key={i} className="flex items-center gap-2 text-[11px] text-muted-foreground">
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-secondary text-[9px] font-semibold text-muted-foreground/70">
                      {i + 1}
                    </span>
                    <span>{step}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Tags and Metadata */}
            <div className="flex items-center gap-2 text-caption flex-wrap">
              {mission.persona && (
                <span className="inline-flex items-center gap-1 rounded-full border border-border/80 bg-secondary/40 px-2 py-0.5 text-foreground/80 font-medium">
                  <MaterialIcon name="person" size={12} className="text-muted-foreground" />
                  {mission.persona}
                </span>
              )}
              {mission.estimatedTimeSeconds && (
                <span className="inline-flex items-center gap-1 text-muted-foreground/70">
                  <MaterialIcon name="schedule" size={12} />
                  ~{mission.estimatedTimeSeconds}s
                </span>
              )}
              {mission.routeAnalysis && (
                <span className={cn(
                  "inline-flex items-center gap-1 text-xs",
                  mission.routeAnalysis.accessible ? "text-green-600" : "text-red-500"
                )}>
                  <MaterialIcon name={mission.routeAnalysis.accessible ? "check_circle" : "error"} size={12} />
                  {mission.routeAnalysis.accessible ? "Accessible" : "Blocked"}
                </span>
              )}
              {mission.successCondition && (
                <span className="hidden sm:inline-flex items-center gap-1 text-muted-foreground/70 text-xs">
                  <MaterialIcon name="verified" size={12} />
                  {formatSuccessCondition(mission.successCondition)}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2 shrink-0 self-center sm:self-start">
          <Button
            variant="ghost"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              onEdit(mission);
            }}
            className="text-muted-foreground hover:text-foreground h-8 px-2.5 text-caption font-medium border border-border/60 hover:bg-secondary/40"
            aria-label={`Adjust ${mission.title}`}
          >
            <MaterialIcon name="tune" size={14} />
            Adjust
          </Button>
          <Button
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              onRun(mission.id);
            }}
            className="h-8 px-3 text-caption font-medium"
          >
            Run
            <MaterialIcon name="arrow_forward" size={14} />
          </Button>
        </div>
      </div>
    </div>
  );
}
