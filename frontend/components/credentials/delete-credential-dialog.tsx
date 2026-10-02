"use client";

import type { Credential } from "@/lib/types";
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

interface DeleteCredentialDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  credential: Credential | null;
  onConfirm: () => void;
  loading?: boolean;
  error?: string | null;
}

export function DeleteCredentialDialog({
  open,
  onOpenChange,
  credential,
  onConfirm,
  loading = false,
  error = null,
}: DeleteCredentialDialogProps) {
  if (!credential) return null;

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
            <DialogTitle>Delete test account?</DialogTitle>
          </div>
          <DialogDescription>
            Kova will no longer be able to use &ldquo;{credential.name}&rdquo;
            for future missions.
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
          >
            {loading ? (
              <>
                <MaterialIcon
                  name="progress_activity"
                  size={14}
                  className="animate-spin"
                />
                Deleting...
              </>
            ) : (
              <>
                <MaterialIcon name="delete" size={14} />
                Delete account
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
