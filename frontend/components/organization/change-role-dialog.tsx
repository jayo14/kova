"use client";

import { useState } from "react";
import type { OrganizationMember, MemberRole, UpdateMemberRoleInput } from "@/lib/types";
import { memberRoleLabels } from "@/lib/types";
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

interface ChangeRoleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  member: OrganizationMember | null;
  onChangeRole: (input: UpdateMemberRoleInput) => void;
  loading?: boolean;
}

export function ChangeRoleDialog({
  open,
  onOpenChange,
  member,
  onChangeRole,
  loading = false,
}: ChangeRoleDialogProps) {
  const [role, setRole] = useState<MemberRole>(member?.role ?? "member");

  if (!member || member.role === "owner") return null;

  const handleSave = () => {
    onChangeRole({ memberId: member.id, role });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Change role</DialogTitle>
          <DialogDescription>
            Update {member.name}&apos;s role in this workspace.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5 py-1">
          <label htmlFor="change-role-select" className="text-body-xs font-medium text-foreground">
            Role
          </label>
          <select
            id="change-role-select"
            value={role}
            onChange={(e) => setRole(e.target.value as MemberRole)}
            disabled={loading}
            className="h-9 w-full min-w-0 rounded-xl border border-input bg-card/60 px-3 py-1 text-body-sm transition-colors outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/20 disabled:opacity-50"
          >
            <option value="member">{memberRoleLabels.member}</option>
          </select>
          <p className="text-caption text-muted-foreground/80 pt-0.5">
            Workspace ownership cannot be transferred through role assignment.
          </p>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <DialogClose render={<Button variant="ghost" disabled={loading} />}>
            Cancel
          </DialogClose>
          <Button onClick={handleSave} disabled={loading} className="gap-1.5 rounded-xl shadow-sm">
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
  );
}
