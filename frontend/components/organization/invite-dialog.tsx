"use client";

import { useState } from "react";
import type { InviteMemberInput, MemberRole } from "@/lib/types";
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
import { Button } from "@/components/ui/button";
import { MaterialIcon } from "@/components/shared/material-icon";

interface InviteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onInvite: (input: InviteMemberInput) => void;
  loading?: boolean;
  error?: string | null;
}

export function InviteDialog({
  open,
  onOpenChange,
  onInvite,
  loading = false,
  error = null,
}: InviteDialogProps) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<MemberRole>("member");
  const [fieldError, setFieldError] = useState<string | null>(null);

  const handleSubmit = () => {
    if (!email.trim()) {
      setFieldError("Enter an email address.");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setFieldError("Enter a valid email address.");
      return;
    }
    setFieldError(null);
    onInvite({ email: email.trim(), role });
  };

  const handleClose = () => {
    setEmail("");
    setRole("member");
    setFieldError(null);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Invite someone</DialogTitle>
          <DialogDescription>
            They&apos;ll receive an invitation to join this workspace.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {(error || fieldError) && (
            <div
              role="alert"
              className="flex items-center gap-2 rounded-xl bg-destructive/10 px-3.5 py-2.5 text-body-sm text-destructive"
            >
              <MaterialIcon
                name="error"
                size={16}
                className="text-destructive shrink-0"
              />
              <p>{fieldError || error}</p>
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="invite-email" className="text-body-xs font-medium text-foreground">
              Email
            </label>
            <Input
              id="invite-email"
              type="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setFieldError(null);
              }}
              placeholder="teammate@example.com"
              disabled={loading}
              aria-invalid={!!fieldError}
              aria-describedby={fieldError ? "invite-email-error" : undefined}
              required
            />
            {fieldError && (
              <p id="invite-email-error" className="text-caption text-destructive">
                {fieldError}
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <label htmlFor="invite-role" className="text-body-xs font-medium text-foreground">
              Role
            </label>
            <select
              id="invite-role"
              value={role}
              onChange={(e) => setRole(e.target.value as MemberRole)}
              disabled={loading}
              className="h-9 w-full min-w-0 rounded-xl border border-input bg-card/60 px-3 py-1 text-body-sm transition-colors outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/20 disabled:opacity-50"
            >
              <option value="member">Member</option>
              <option value="owner">Owner</option>
            </select>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <DialogClose render={<Button variant="ghost" disabled={loading} />}>
            Cancel
          </DialogClose>
          <Button onClick={handleSubmit} disabled={loading} className="gap-1.5 rounded-xl shadow-sm">
            {loading ? (
              <>
                <MaterialIcon
                  name="progress_activity"
                  size={14}
                  className="animate-spin"
                />
                Sending...
              </>
            ) : (
              "Send invite"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
