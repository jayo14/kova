"use client";

import { useState, useTransition } from "react";
import type { Mission } from "@/lib/types";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { MaterialIcon } from "@/components/shared/material-icon";

interface AdjustMissionDialogProps {
  mission: Mission;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (
    missionId: string,
    instruction: string,
    updatedFields?: Partial<Mission>
  ) => Promise<void> | void;
}

export function AdjustMissionDialog({
  mission,
  open,
  onOpenChange,
  onSave,
}: AdjustMissionDialogProps) {
  const [isPending, startTransition] = useTransition();
  const [instruction, setInstruction] = useState("");
  const [showMetadata, setShowMetadata] = useState(false);

  const [name, setName] = useState(mission.name);
  const [persona, setPersona] = useState(mission.persona || "");
  const [objective, setObjective] = useState(mission.objective);

  const suggestionExamples = [
    "Use an administrator instead of a student.",
    "Don't upload a new PDF. Use an existing material.",
    "Verify that the results page opens.",
    "Also check that the generated questions contain answers.",
  ];

  const handleSave = () => {
    const trimmedInstruction = instruction.trim();
    if (!trimmedInstruction && !showMetadata) return;

    startTransition(async () => {
      await onSave(
        mission.id,
        trimmedInstruction || "Updated mission details",
        showMetadata
          ? {
              name: name.trim() || mission.name,
              persona: persona.trim() || null,
              objective: objective.trim() || mission.objective,
            }
          : undefined
      );
      setInstruction("");
      onOpenChange(false);
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Adjust mission</DialogTitle>
          <DialogDescription>
            What should Kova change about how it accomplishes this mission?
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <label
              htmlFor="adjust-instruction"
              className="text-body-xs font-medium text-foreground"
            >
              Instruction
            </label>
            <Textarea
              id="adjust-instruction"
              placeholder='e.g. "Use an administrator instead of a student." or "Verify that checkout page loads."'
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              rows={3}
              className="text-body-sm"
              disabled={isPending}
              aria-label="Adjustment instruction"
              autoFocus
            />
          </div>

          <div className="space-y-1.5">
            <span className="text-caption text-muted-foreground/80">Suggestions:</span>
            <div className="flex flex-wrap gap-1.5">
              {suggestionExamples.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => setInstruction(example)}
                  className="rounded-lg border border-border/70 bg-secondary/30 px-2 py-1 text-caption text-muted-foreground hover:bg-secondary/70 hover:text-foreground transition-colors text-left"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>

          <div className="border-t border-border/60 pt-3">
            <button
              type="button"
              onClick={() => setShowMetadata(!showMetadata)}
              className="flex items-center gap-1 text-body-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              <MaterialIcon
                name={showMetadata ? "expand_less" : "expand_more"}
                size={16}
              />
              <span>{showMetadata ? "Hide details" : "Edit mission fields (name, persona, objective)"}</span>
            </button>

            {showMetadata && (
              <div className="mt-3 space-y-3 pl-2 border-l-2 border-border/60">
                <div className="space-y-1">
                  <label className="text-body-xs font-medium text-foreground">
                    Mission Name
                  </label>
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    disabled={isPending}
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-body-xs font-medium text-foreground">
                    Persona / Role
                  </label>
                  <Input
                    value={persona}
                    onChange={(e) => setPersona(e.target.value)}
                    placeholder="e.g. Student, Admin"
                    disabled={isPending}
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-body-xs font-medium text-foreground">
                    Objective
                  </label>
                  <Textarea
                    value={objective}
                    onChange={(e) => setObjective(e.target.value)}
                    rows={2}
                    disabled={isPending}
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-body-xs font-medium text-foreground">
                    Verification
                  </label>
                  <div className="rounded-md border border-border bg-secondary/30 px-3 py-2 text-caption text-muted-foreground">
                    Machine-verified against live browser state — derived from the
                    journey, not user-editable text.
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 pt-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={isPending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleSave}
            disabled={isPending || (!instruction.trim() && !showMetadata)}
            className="gap-1.5"
          >
            {isPending && (
              <MaterialIcon
                name="progress_activity"
                size={14}
                className="animate-spin"
              />
            )}
            Save adjustment
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
