"use client";

import { useState } from "react";
import { updatePassword } from "@/lib/auth/settings";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { PasswordInput } from "@/components/ui/password-input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";

export function PasswordSection() {
  const [open, setOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const clearPasswords = () => {
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
  };

  const handleUpdate = async () => {
    const cur = currentPassword;
    const next = newPassword;
    const confirm = confirmPassword;

    if (!cur.trim()) {
      setError("Current password is required.");
      return;
    }
    if (!next.trim()) {
      setError("New password is required.");
      return;
    }
    if (next.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    if (next !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    // Zero out password fields immediately to minimize retention in memory
    clearPasswords();
    setLoading(true);
    setError(null);

    try {
      // First verify current password by signing in
      const { createClient } = await import("@/lib/auth/client");
      const supabase = createClient();
      const userRes = await supabase.auth.getUser();
      const email = userRes.data.user?.email ?? "";

      const { error: signInError } = await supabase.auth.signInWithPassword({
        email,
        password: cur,
      });

      if (signInError) {
        setError("Current password is incorrect.");
        return;
      }

      const result = await updatePassword(next);
      if (result.error) {
        setError(result.error);
        return;
      }

      setSuccess(true);
      setTimeout(() => {
        setOpen(false);
        setSuccess(false);
      }, 1500);
    } catch {
      setError("Something went wrong. Try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    clearPasswords();
    setOpen(false);
    setError(null);
    setSuccess(false);
  };

  return (
    <div className="rounded-2xl border border-border/70 bg-card/50 p-6 transition-colors">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-body font-semibold text-foreground">Password</h2>
          <p className="text-caption text-muted-foreground">
            Change the password for your Kova account.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setError(null);
            setOpen(true);
          }}
          className="gap-1.5 rounded-xl shrink-0"
        >
          <MaterialIcon name="lock" size={14} />
          Change password
        </Button>
      </div>

      <div className="space-y-3 pt-2 border-t border-border/50">
        <div>
          <p className="text-caption font-medium uppercase tracking-wider text-muted-foreground/70 mb-1">
            Account password
          </p>
          <div className="flex items-center gap-2">
            <span className="text-body-sm font-mono text-muted-foreground tracking-widest">
              ••••••••••••
            </span>
            <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground/80 font-medium">
              <MaterialIcon name="check_circle" size={13} className="text-emerald-600 dark:text-emerald-400" />
              Saved securely
            </span>
          </div>
        </div>

        {success && (
          <div
            role="status"
            className="flex items-center gap-2 rounded-xl bg-emerald-500/10 px-3.5 py-2 text-body-sm text-emerald-700 dark:text-emerald-400"
          >
            <MaterialIcon name="check_circle" size={16} className="shrink-0" />
            <p>Password updated.</p>
          </div>
        )}
      </div>

      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Change password</DialogTitle>
            <DialogDescription>
              Enter your current password and choose a new one.
            </DialogDescription>
          </DialogHeader>

          {success ? (
            <div
              role="status"
              className="flex items-center gap-2 rounded-xl bg-emerald-500/10 px-3.5 py-2.5 text-body-sm text-emerald-700 dark:text-emerald-400"
            >
              <MaterialIcon
                name="check_circle"
                size={16}
                className="shrink-0"
              />
              <p>Password updated.</p>
            </div>
          ) : (
            <div className="space-y-4 py-1">
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

              <div className="space-y-1.5">
                <label
                  htmlFor="current-password"
                  className="text-body-xs font-medium text-foreground"
                >
                  Current password
                </label>
                <PasswordInput
                  id="current-password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  placeholder="Enter current password"
                  disabled={loading}
                  autoComplete="current-password"
                />
              </div>

              <div className="space-y-1.5">
                <label
                  htmlFor="new-password"
                  className="text-body-xs font-medium text-foreground"
                >
                  New password
                </label>
                <PasswordInput
                  id="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="At least 6 characters"
                  disabled={loading}
                  autoComplete="new-password"
                />
              </div>

              <div className="space-y-1.5">
                <label
                  htmlFor="confirm-password"
                  className="text-body-xs font-medium text-foreground"
                >
                  Confirm new password
                </label>
                <PasswordInput
                  id="confirm-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Repeat new password"
                  disabled={loading}
                  autoComplete="new-password"
                />
              </div>
            </div>
          )}

          <DialogFooter className="gap-2 sm:gap-0">
            <DialogClose render={<Button variant="ghost" disabled={loading} />}>
              Cancel
            </DialogClose>
            {!success && (
              <Button
                onClick={handleUpdate}
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
                    Updating password...
                  </>
                ) : (
                  "Update password"
                )}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
