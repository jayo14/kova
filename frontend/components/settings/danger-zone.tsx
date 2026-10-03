"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { deleteAccount, signOut } from "@/lib/auth/settings";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import type { User } from "@/lib/auth/custom";

interface DangerZoneProps {
  user: User;
}

export function DangerZone({ user }: DangerZoneProps) {
  const router = useRouter();
  const [step, setStep] = useState<"idle" | "confirm" | "email">("idle");
  const [emailConfirm, setEmailConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canDelete = emailConfirm.trim().toLowerCase() === user.email?.toLowerCase();

  const handleDelete = async () => {
    if (!canDelete || loading) return;
    setLoading(true);
    setError(null);
    try {
      const result = await deleteAccount();
      if (result.error) {
        setError("We couldn't delete your account. Try again.");
        setLoading(false);
        return;
      }
      await signOut();
      router.push("/");
      router.refresh();
    } catch {
      setError("We couldn't delete your account. Try again.");
      setLoading(false);
    }
  };

  const handleClose = () => {
    setStep("idle");
    setEmailConfirm("");
    setError(null);
    setLoading(false);
  };

  return (
    <div className="rounded-2xl border border-destructive/25 bg-destructive/5 p-6 transition-colors">
      <div className="mb-4">
        <h2 className="text-body font-semibold text-destructive">Danger zone</h2>
        <p className="text-caption text-muted-foreground">
          Actions here permanently affect your Kova account.
        </p>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 rounded-xl border border-destructive/20 bg-card p-4">
        <div>
          <p className="text-body-sm font-medium text-foreground">
            Delete account
          </p>
          <p className="text-caption text-muted-foreground">
            Permanently delete your Kova account and associated data.
          </p>
        </div>
        <Button
          variant="destructive"
          size="sm"
          onClick={() => setStep("confirm")}
          className="shrink-0 gap-1.5 rounded-xl shadow-sm"
        >
          <MaterialIcon name="delete" size={14} />
          Delete account
        </Button>
      </div>

      {/* Step 1: Initial confirmation */}
      <Dialog
        open={step === "confirm"}
        onOpenChange={(open) => {
          if (!open) handleClose();
        }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <div className="flex items-center gap-2 mb-2">
              <MaterialIcon
                name="warning"
                size={20}
                className="text-destructive"
              />
              <DialogTitle>Delete your account?</DialogTitle>
            </div>
            <DialogDescription>
              This will permanently remove your Kova account and associated
              workspace data. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <DialogClose render={<Button variant="ghost" />}>
              Cancel
            </DialogClose>
            <Button
              variant="destructive"
              onClick={() => setStep("email")}
              className="gap-1.5 rounded-xl shadow-sm"
            >
              Continue
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Step 2: Email confirmation */}
      <Dialog
        open={step === "email"}
        onOpenChange={(open) => {
          if (!open) handleClose();
        }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Confirm account deletion</DialogTitle>
            <DialogDescription>
              Enter your email to confirm:{" "}
              <strong className="text-foreground">{user.email}</strong>
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

          <div className="space-y-1.5 py-1">
            <label
              htmlFor="delete-email"
              className="text-body-xs font-medium text-foreground"
            >
              Email address
            </label>
            <Input
              id="delete-email"
              type="email"
              value={emailConfirm}
              onChange={(e) => setEmailConfirm(e.target.value)}
              placeholder={user.email ?? ""}
              disabled={loading}
              autoFocus
            />
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <DialogClose render={<Button variant="ghost" disabled={loading} />}>
              Cancel
            </DialogClose>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={!canDelete || loading}
              className="gap-1.5 rounded-xl shadow-sm"
            >
              {loading ? (
                <>
                  <MaterialIcon
                    name="progress_activity"
                    size={14}
                    className="animate-spin"
                  />
                  Deleting account...
                </>
              ) : (
                "Delete my account"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
