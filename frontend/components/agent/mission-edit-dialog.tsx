"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MaterialIcon } from "@/components/shared/material-icon";
// Input still used for title/persona fields above
import type { SuggestedMission } from "@/lib/types";

interface MissionEditDialogProps {
  mission: SuggestedMission | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (updatedMission: SuggestedMission) => void;
}

interface MissionEditFormProps {
  mission: SuggestedMission;
  onSave: (updatedMission: SuggestedMission) => void;
  onCancel: () => void;
}

function MissionEditForm({ mission, onSave, onCancel }: MissionEditFormProps) {
  const [title, setTitle] = useState(mission.title || "");
  const [objective, setObjective] = useState(
    mission.objective || mission.description || ""
  );
  const [persona, setPersona] = useState(mission.persona || "Student");

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;

    // NOTE: successCondition is intentionally NOT editable here. It is a
    // structured, machine-verifiable object produced by deterministic journey
    // synthesis. Letting users overwrite it with free text would break the
    // verification contract (unknown conditions must fail closed, not pass).
    onSave({
      ...mission,
      title: title.trim(),
      objective: objective.trim(),
      description: objective.trim() || mission.description,
      persona: persona.trim(),
    });

    onCancel();
  };

  return (
    <>
      <DialogHeader>
        <div className="flex items-center gap-2 mb-1">
          <MaterialIcon name="tune" size={18} className="text-primary" />
          <DialogTitle className="text-body-lg font-semibold text-foreground">
            Adjust Journey
          </DialogTitle>
        </div>
        <DialogDescription className="text-body-sm text-muted-foreground">
          Adjust the goal or persona for Kova. Kova will figure out the actions and selectors automatically.
        </DialogDescription>
      </DialogHeader>

      <form onSubmit={handleSave} className="space-y-4 py-2">
        <div className="space-y-1.5">
          <label className="text-caption font-medium text-foreground">
            Journey name
          </label>
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Generate a quiz from a PDF"
            required
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-caption font-medium text-foreground">
            Objective (natural language)
          </label>
          <textarea
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            placeholder="Describe what the agent should accomplish"
            rows={3}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-body-sm shadow-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            required
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-caption font-medium text-foreground">
              Persona
            </label>
            <Input
              value={persona}
              onChange={(e) => setPersona(e.target.value)}
              placeholder="e.g. Student, Lecturer, Admin"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-caption font-medium text-foreground">
              Credential context
            </label>
            <div className="h-9 rounded-md border border-border bg-secondary/30 px-3 flex items-center text-caption text-muted-foreground truncate">
              Current test session
            </div>
          </div>
        </div>

        <div className="space-y-1.5">
          <label className="text-caption font-medium text-foreground">
            Verification
          </label>
          <div className="rounded-md border border-border bg-secondary/30 px-3 py-2 text-caption text-muted-foreground">
            Kova verifies the journey outcome against the browser state it observes
            (visible content, URL changes, result counts). Verification is derived
            from the journey and cannot be edited as free text.
          </div>
        </div>

        <DialogFooter className="pt-2">
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit">
            Save adjustments
          </Button>
        </DialogFooter>
      </form>
    </>
  );
}

export function MissionEditDialog({
  mission,
  open,
  onOpenChange,
  onSave,
}: MissionEditDialogProps) {
  if (!mission) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <MissionEditForm
          key={mission.id}
          mission={mission}
          onSave={onSave}
          onCancel={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}
