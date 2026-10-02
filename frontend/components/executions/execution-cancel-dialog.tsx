"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { MaterialIcon } from "@/components/shared/material-icon";

interface ExecutionCancelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  missionName: string;
  onConfirm: () => void;
  loading?: boolean;
}

export function ExecutionCancelDialog({
  open,
  onOpenChange,
  missionName,
  onConfirm,
  loading = false,
}: ExecutionCancelDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Stop this execution?</DialogTitle>
          <DialogDescription className="text-body-sm text-muted-foreground pt-1">
            Kova will stop working on &ldquo;{missionName}&rdquo;.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 sm:gap-2 pt-2">
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={loading}
          >
            Keep running
          </Button>
          <Button
            variant="outline"
            onClick={onConfirm}
            disabled={loading}
            className="gap-1.5 border-border/80 text-foreground hover:bg-secondary/40"
          >
            {loading ? (
              <MaterialIcon
                name="progress_activity"
                size={14}
                className="animate-spin"
              />
            ) : (
              <MaterialIcon name="stop" size={14} />
            )}
            Stop execution
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
