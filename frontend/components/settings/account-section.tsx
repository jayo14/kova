"use client";

import { useState } from "react";
import type { User } from "@/lib/auth/custom";
import { updateProfile } from "@/lib/auth/settings";
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

interface AccountSectionProps {
  user: User;
  onUserUpdate: (user: User) => void;
}

export function AccountSection({ user, onUserUpdate }: AccountSectionProps) {
  const [editOpen, setEditOpen] = useState(false);
  const [name, setName] = useState(user.user_metadata?.name ?? "");
  const [email, setEmail] = useState(user.email ?? "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const displayName =
    user.user_metadata?.name || user.email?.split("@")[0] || "User";

  const handleSave = async () => {
    if (!name.trim()) {
      setError("Enter a name.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const emailChanged = email.trim().toLowerCase() !== user.email?.toLowerCase();
      const result = await updateProfile({
        name: name.trim(),
        email: emailChanged ? email.trim() : undefined,
      });

      if (result.error) {
        setError(result.error);
        return;
      }

      if (result.user) {
        onUserUpdate(result.user);
      } else {
        const updated = { ...user };
        if (user.user_metadata) {
          updated.user_metadata = { ...user.user_metadata, name: name.trim() };
        }
        onUserUpdate(updated);
      }

      setEditOpen(false);
      setSuccessMessage(
        emailChanged
          ? "Profile updated. Check your inbox to confirm your new email address."
          : "Profile updated."
      );
      setTimeout(() => setSuccessMessage(null), 5000);
    } catch {
      setError("Something went wrong. Try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-2xl border border-border/70 bg-card/50 p-6 transition-colors">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-body font-semibold text-foreground">Account</h2>
          <p className="text-caption text-muted-foreground">
            Your personal Kova account details.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setName(user.user_metadata?.name ?? "");
            setEmail(user.email ?? "");
            setError(null);
            setEditOpen(true);
          }}
          className="gap-1.5 rounded-xl shrink-0"
        >
          <MaterialIcon name="edit" size={14} />
          Edit profile
        </Button>
      </div>

      <div className="space-y-4 pt-2 border-t border-border/50">
        <div>
          <p className="text-caption font-medium uppercase tracking-wider text-muted-foreground/70 mb-1">
            Name
          </p>
          <p className="text-body-sm font-medium text-foreground">{displayName}</p>
        </div>
        <div>
          <p className="text-caption font-medium uppercase tracking-wider text-muted-foreground/70 mb-1">
            Email
          </p>
          <p className="text-body-sm font-mono text-[13px] text-foreground">{user.email}</p>
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
            <DialogTitle>Edit profile</DialogTitle>
            <DialogDescription>Update your personal account details.</DialogDescription>
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

          <div className="space-y-4 py-1">
            <div className="space-y-1.5">
              <label
                htmlFor="profile-name"
                className="text-body-xs font-medium text-foreground"
              >
                Name
              </label>
              <Input
                id="profile-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
                disabled={loading}
                required
              />
            </div>

            <div className="space-y-1.5">
              <label
                htmlFor="profile-email"
                className="text-body-xs font-medium text-foreground"
              >
                Email
              </label>
              <Input
                id="profile-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                disabled={loading}
                required
              />
              <p className="text-caption text-muted-foreground/80">
                Changing your email requires confirming the link sent to your new address.
              </p>
            </div>
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
    </div>
  );
}
