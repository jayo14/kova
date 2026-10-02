"use client";

import type { OrganizationMember } from "@/lib/types";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { MaterialIcon } from "@/components/shared/material-icon";

interface RemoveMemberDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  member: OrganizationMember | null;
  onConfirm: () => void;
  loading?: boolean;
  error?: string | null;
}

export function RemoveMemberDialog({
  open,
  onOpenChange,
  member,
  onConfirm,
  loading = false,
  error = null,
}: RemoveMemberDialogProps) {
  if (!member || member.role === "owner" || member.isCurrentUser) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <div className="flex items-center gap-2 mb-2">
            <MaterialIcon
              name="warning"
              size={20}
              className="text-destructive"
            />
            <DialogTitle>Remove member?</DialogTitle>
          </div>
          <DialogDescription>
            {member.name} will no longer have access to this workspace and its
            projects.
          </DialogDescription>
        </DialogHeader>

        {error && (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-xl bg-destructive/10 px-3.5 py-2.5 text-body-sm text-destructive"
          >
            <MaterialIcon
              name="error"
              size={16}
              className="text-destructive shrink-0"
            />
            <p>{error}</p>
          </div>
        )}

        <DialogFooter className="gap-2 sm:gap-0">
          <DialogClose render={<Button variant="ghost" disabled={loading} />}>
            Cancel
          </DialogClose>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={loading}
            className="gap-1.5 rounded-xl shadow-sm"
          >
            {loading ? (
              <>
                <MaterialIcon
                  name="progress_activity"
                  size={14}
                  className="animate-spin"
                />
                Removing...
              </>
            ) : (
              <>
                <MaterialIcon name="person_remove" size={14} />
                Remove member
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
