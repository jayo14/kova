"use client";

import { useState } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { MissionCard } from "./mission-card";
import { MissionEditDialog } from "./mission-edit-dialog";
import type { SuggestedMission } from "@/lib/types";
import { cn } from "@/lib/utils";

interface MissionSuggestionsProps {
  missions: SuggestedMission[];
  recommendation?: string;
  projectName?: string;
  onRun: (missionIds: string[], parallel: boolean) => void;
  onOpenProject?: () => void;
  onUpdateMission?: (mission: SuggestedMission) => void;
}

export function MissionSuggestions({
  missions,
  recommendation,
  projectName,
  onRun,
  onOpenProject,
  onUpdateMission,
}: MissionSuggestionsProps) {
  // Default selection: recommended missions or first mission
  const [selected, setSelected] = useState<Set<string>>(() => {
    const recs = missions.filter((m) => m.recommended).map((m) => m.id);
    return new Set(recs.length > 0 ? recs : missions.slice(0, 1).map((m) => m.id));
  });

  const [editingMission, setEditingMission] = useState<SuggestedMission | null>(null);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [parallelExecution, setParallelExecution] = useState(true);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleSelectAll = () => {
    if (selected.size === missions.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(missions.map((m) => m.id)));
    }
  };

  const handleRun = () => {
    const missionIds = selected.size === 0
      ? missions.slice(0, 1).map((m) => m.id)
      : Array.from(selected);
    onRun(missionIds, parallelExecution && missionIds.length > 1);
  };

  const handleEdit = (mission: SuggestedMission) => {
    setEditingMission(mission);
    setEditDialogOpen(true);
  };

  const handleSaveEdit = (updated: SuggestedMission) => {
    if (onUpdateMission) {
      onUpdateMission(updated);
    }
  };

  const allSelected = selected.size === missions.length && missions.length > 0;

  return (
    <div className="w-full max-w-2xl mx-auto animate-in fade-in zoom-in-95 duration-300">
      {/* Editorial Header */}
      <div className="text-center mb-8">
        <div className="inline-flex items-center gap-2 rounded-full border border-border bg-secondary/40 px-3 py-1 text-caption text-muted-foreground mb-4">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-600" />
          <span>{projectName ? `${projectName} is ready` : "Exploration complete"}</span>
        </div>

        <h2 className="text-h2 font-semibold text-foreground mb-2">
          I found {missions.length} useful journeys.
        </h2>

        {recommendation ? (
          <p className="text-body-sm text-muted-foreground max-w-lg mx-auto leading-relaxed">
            {recommendation}
          </p>
        ) : (
          <p className="text-body-sm text-muted-foreground">
            Select the journeys you want Kova to run or start with the recommendation.
          </p>
        )}
      </div>

      {/* Mission Selection Controls */}
      <div className="flex items-center justify-between px-1 mb-3">
        <button
          type="button"
          onClick={handleSelectAll}
          className="text-caption font-medium text-muted-foreground hover:text-foreground transition-colors"
        >
          {allSelected ? "Deselect all" : `Select all (${missions.length})`}
        </button>

        <span className="text-caption font-mono text-muted-foreground/70">
          {selected.size} of {missions.length} selected
        </span>
      </div>

      {/* Suggested Mission Cards */}
      <div className="space-y-3 mb-8">
        {missions.map((mission) => (
          <MissionCard
            key={mission.id}
            mission={mission}
            selected={selected.has(mission.id)}
            onSelect={toggle}
            onRun={(id) => onRun([id], false)}
            onEdit={handleEdit}
          />
        ))}
      </div>

      <Separator className="mb-6" />

      {/* Bottom Action Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 bg-card border border-border p-4 rounded-2xl shadow-xs">
        <div>
          <p className="text-body-sm font-medium text-foreground">
            {selected.size === 0
              ? "No journey selected"
              : `Ready to run ${selected.size} journey${selected.size > 1 ? "s" : ""}`}
          </p>
          <p className="text-caption text-muted-foreground">
            Kova will execute the steps autonomously in an isolated session
          </p>
        </div>

        <div className="flex items-center gap-3 w-full sm:w-auto justify-end">
          {/* Parallel Execution Toggle (only show when multiple selected) */}
          {selected.size > 1 && (
            <div className="flex items-center gap-2">
              <label htmlFor="parallel-toggle" className="text-caption text-muted-foreground">
                Parallel
              </label>
              <button
                id="parallel-toggle"
                type="button"
                role="switch"
                aria-checked={parallelExecution}
                onClick={() => setParallelExecution(!parallelExecution)}
                className={cn(
                  "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
                  parallelExecution ? "bg-primary" : "bg-muted"
                )}
              >
                <span
                  className={cn(
                    "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow-lg ring-0 transition duration-200 ease-in-out",
                    parallelExecution ? "translate-x-4" : "translate-x-0"
                  )}
                />
              </button>
            </div>
          )}

          {onOpenProject && (
            <Button
              variant="outline"
              size="default"
              onClick={onOpenProject}
              className="flex-1 sm:flex-initial"
            >
              Open project
            </Button>
          )}

          <Button
            size="default"
            onClick={handleRun}
            className="flex-1 sm:flex-initial font-medium px-5"
          >
            {selected.size > 1 ? `Run ${selected.size} journeys` : "Let Kova run it"}
            <MaterialIcon name="arrow_forward" size={16} />
          </Button>
        </div>
      </div>

      {/* Adjustment Dialog */}
      <MissionEditDialog
        mission={editingMission}
        open={editDialogOpen}
        onOpenChange={setEditDialogOpen}
        onSave={handleSaveEdit}
      />
    </div>
  );
}
