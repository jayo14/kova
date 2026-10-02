"use client";

import { useState } from "react";
import type { Organization, UpdateOrganizationInput } from "@/lib/types";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

interface WorkspaceInfoProps {
  organization: Organization;
  onUpdate: (input: UpdateOrganizationInput) => void;
  loading?: boolean;
  canManage?: boolean;
}

export function WorkspaceInfo({
  organization,
  onUpdate,
  loading = false,
  canManage = true,
}: WorkspaceInfoProps) {
  const [editOpen, setEditOpen] = useState(false);
  const [name, setName] = useState(organization.name);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const handleSave = () => {
    if (!name.trim()) {
      setError("Enter a workspace name.");
      return;
    }
    onUpdate({ name: name.trim() });
    setEditOpen(false);
    setError(null);
    setSuccessMessage("Workspace updated.");
    setTimeout(() => {
      setSuccessMessage(null);
    }, 4000);
  };

  return (
    <div className="rounded-2xl border border-border/70 bg-card/50 p-6 transition-colors">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-body font-semibold text-foreground">Workspace</h2>
          <p className="text-caption text-muted-foreground">
            The workspace details associated with your projects and credentials.
          </p>
        </div>
        {canManage && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setName(organization.name);
              setError(null);
              setEditOpen(true);
            }}
            className="gap-1.5 rounded-xl shrink-0"
          >
            <MaterialIcon name="edit" size={14} />
            Edit
          </Button>
        )}
      </div>

      <div className="space-y-3 pt-2 border-t border-border/50">
        <div>
          <p className="text-caption font-medium uppercase tracking-wider text-muted-foreground/70 mb-1">
            Workspace name
          </p>
          <p className="text-body-sm font-medium text-foreground">
            {organization.name}
          </p>
        </div>

        {successMessage && (
          <div
            role="status"
            className="flex items-center gap-2 rounded-xl bg-emerald-500/10 px-3.5 py-2 text-body-sm text-emerald-700 dark:text-emerald-400"
          >
            <MaterialIcon name="check_circle" size={16} className="shrink-0" />
            <p>{successMessage}</p>
          </div>
        )}
      </div>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Edit workspace</DialogTitle>
            <DialogDescription>
              Update your workspace name.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-1.5">
            <label htmlFor="org-name" className="text-body-sm text-foreground">
              Workspace name
            </label>
            <Input
              id="org-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Workspace name"
              disabled={loading}
              aria-invalid={!!error}
            />
            {error && (
              <p className="text-caption text-destructive">{error}</p>
            )}
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <DialogClose render={<Button variant="ghost" />}>
              Cancel
            </DialogClose>
            <Button onClick={handleSave} disabled={loading}>
              {loading ? (
                <>
                  <MaterialIcon
                    name="progress_activity"
                    size={14}
                    className="animate-spin"
                  />
                  Saving...
                </>
              ) : (
                "Save"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
