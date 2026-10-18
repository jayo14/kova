"use client";

import { useState, useTransition, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import type { Project } from "@/lib/types";
import { updateProject, deleteProject } from "@/lib/api/projects";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { MaterialIcon } from "@/components/shared/material-icon";

interface ProjectSettingsDialogProps {
  project: Project;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onProjectUpdated?: (updated: Project) => void;
  onProjectDeleted?: () => void;
}

export function ProjectSettingsDialog({
  project,
  open,
  onOpenChange,
  onProjectUpdated,
  onProjectDeleted,
}: ProjectSettingsDialogProps) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  const [name, setName] = useState(project.name);
  const [baseUrl, setBaseUrl] = useState(project.baseUrl);
  const [description, setDescription] = useState(project.description || "");
  const [productGoal, setProductGoal] = useState(project.productGoal || "");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [envTarget, setEnvTarget] = useState<"development" | "staging" | "production">(
    project.envConfig?.target || "staging"
  );
  const [maxDuration, setMaxDuration] = useState(
    project.executionLimits?.maxDurationSeconds ?? 300
  );
  const [maxTurns, setMaxTurns] = useState(
    project.executionLimits?.maxAgentTurns ?? 60
  );
  const [productionAllowed, setProductionAllowed] = useState(
    project.safetyRestrictions?.productionAccessAllowed ?? false
  );
  const [paymentAllowed, setPaymentAllowed] = useState(
    project.safetyRestrictions?.paymentActionsAllowed ?? false
  );
  const [accountDeletionAllowed, setAccountDeletionAllowed] = useState(
    project.safetyRestrictions?.accountDeletionAllowed ?? false
  );
  const [error, setError] = useState<string | null>(null);

  const [isDeleting, setIsDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);

    const trimmedName = name.trim();
    const trimmedUrl = baseUrl.trim();

    if (!trimmedName) {
      setError("Product name is required.");
      return;
    }

    if (!trimmedUrl) {
      setError("Canonical URL is required.");
      return;
    }

    try {
      new URL(trimmedUrl);
    } catch {
      setError("Please enter a valid URL (e.g. https://example.com).");
      return;
    }

    if (productionAllowed && envTarget === "production" && !description.includes("I ACKNOWLEDGE production access")) {
      setError("Production access requires explicit acknowledgment: include 'I ACKNOWLEDGE production access' in the description.");
      return;
    }

    startTransition(async () => {
      const updated = await updateProject(project.id, {
        name: trimmedName,
        baseUrl: trimmedUrl,
        description: description.trim() || undefined,
        productGoal: productGoal.trim() || undefined,
        envConfig: { target: envTarget },
        executionLimits: {
          maxDurationSeconds: Number(maxDuration),
          maxAgentTurns: Number(maxTurns),
        },
        safetyRestrictions: {
          productionAccessAllowed: productionAllowed,
          paymentActionsAllowed: paymentAllowed,
          accountDeletionAllowed: accountDeletionAllowed,
        },
      });

      if (!updated) {
        setError("Failed to update product. Please try again.");
        return;
      }

      onProjectUpdated?.(updated);
      onOpenChange(false);
      router.refresh();
    });
  };

  const handleDelete = async () => {
    setIsDeleting(true);
    setError(null);

    const success = await deleteProject(project.id);
    setIsDeleting(false);

    if (!success) {
      setError("Failed to delete product. Please try again.");
      return;
    }

    onOpenChange(false);
    if (onProjectDeleted) {
      onProjectDeleted();
    } else {
      router.push("/projects");
      router.refresh();
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Product Settings</DialogTitle>
          <DialogDescription>
            Update product details or manage settings for {project.name}.
          </DialogDescription>
        </DialogHeader>

        {error && (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-body-sm text-destructive"
          >
            <MaterialIcon name="error" size={16} />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label
              htmlFor="settings-project-name"
              className="text-body-xs font-medium text-foreground"
            >
              Product name
            </label>
            <Input
              id="settings-project-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Acme Dashboard"
              disabled={isPending || isDeleting}
              required
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="settings-project-url"
              className="text-body-xs font-medium text-foreground"
            >
              Canonical URL
            </label>
            <Input
              id="settings-project-url"
              type="url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://app.example.com"
              disabled={isPending || isDeleting}
              required
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="settings-project-desc"
              className="text-body-xs font-medium text-foreground"
            >
              Description (optional)
            </label>
            <Textarea
              id="settings-project-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Brief description of what this product does..."
              disabled={isPending || isDeleting}
              rows={3}
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="settings-project-goal"
              className="text-body-xs font-medium text-foreground"
            >
              Product Goal (natural-language verification intent)
            </label>
            <Textarea
              id="settings-project-goal"
              value={productGoal}
              onChange={(e) => setProductGoal(e.target.value)}
              placeholder="e.g. Verify user signup, onboarding, and workspace configuration without regressions..."
              disabled={isPending || isDeleting}
              rows={2}
            />
          </div>

          <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
            <button
              type="button"
              className="flex w-full items-center justify-between text-body-xs font-semibold text-foreground"
              onClick={() => setShowAdvanced((v) => !v)}
            >
              <span className="flex items-center gap-1.5">
                <MaterialIcon name="tune" size={16} />
                Advanced environment & safety settings
              </span>
              <MaterialIcon
                name={showAdvanced ? "expand_less" : "expand_more"}
                size={18}
              />
            </button>

            {showAdvanced && (
              <div className="mt-3 space-y-3 pt-3 border-t border-border/40 text-body-xs">
                <div className="space-y-1">
                  <label className="font-medium text-foreground">Target Environment</label>
                  <select
                    className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-body-xs"
                    value={envTarget}
                    onChange={(e) => setEnvTarget(e.target.value as any)}
                    disabled={isPending || isDeleting}
                  >
                    <option value="development">Development</option>
                    <option value="staging">Staging (default)</option>
                    <option value="production">Production</option>
                  </select>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <label className="font-medium text-foreground">Max Duration (s)</label>
                    <Input
                      type="number"
                      min={30}
                      max={1800}
                      value={maxDuration}
                      onChange={(e) => setMaxDuration(Number(e.target.value))}
                      disabled={isPending || isDeleting}
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="font-medium text-foreground">Max Agent Turns</label>
                    <Input
                      type="number"
                      min={1}
                      max={100}
                      value={maxTurns}
                      onChange={(e) => setMaxTurns(Number(e.target.value))}
                      disabled={isPending || isDeleting}
                    />
                  </div>
                </div>

                <div className="space-y-2 pt-2">
                  <span className="font-medium text-foreground block">Safety restrictions</span>

                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={productionAllowed}
                      onChange={(e) => setProductionAllowed(e.target.checked)}
                      disabled={isPending || isDeleting}
                    />
                    <span>Allow navigation to production environments</span>
                  </label>
                  {productionAllowed && (
                    <p className="text-[11px] text-amber-500 pl-6">
                      ⚠️ Caution: Requires description acknowledgment when target environment is production.
                    </p>
                  )}

                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={paymentAllowed}
                      onChange={(e) => setPaymentAllowed(e.target.checked)}
                      disabled={isPending || isDeleting}
                    />
                    <span>Allow payment and checkout actions</span>
                  </label>
                  {paymentAllowed && (
                    <p className="text-[11px] text-amber-500 pl-6">
                      ⚠️ Warning: Payment actions may trigger financial transactions.
                    </p>
                  )}

                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={accountDeletionAllowed}
                      onChange={(e) => setAccountDeletionAllowed(e.target.checked)}
                      disabled={isPending || isDeleting}
                    />
                    <span>Allow account deletion operations</span>
                  </label>
                </div>
              </div>
            )}
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={isPending || isDeleting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={isPending || isDeleting}
              className="gap-1.5"
            >
              {isPending && (
                <MaterialIcon
                  name="progress_activity"
                  size={16}
                  className="animate-spin"
                />
              )}
              Save changes
            </Button>
          </div>
        </form>

        <div className="mt-4 border-t border-border pt-4">
          <div className="rounded-xl border border-destructive/20 bg-destructive/5 p-4">
            <h4 className="text-body-sm font-semibold text-destructive mb-1 flex items-center gap-1.5">
              <MaterialIcon name="warning" size={16} />
              Danger zone
            </h4>
            <p className="text-body-xs text-muted-foreground mb-3 leading-relaxed">
              Permanently delete this product and all associated missions and execution evidence.
              This action cannot be undone.
            </p>

            {confirmDelete ? (
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  onClick={handleDelete}
                  disabled={isDeleting}
                  className="gap-1.5"
                >
                  {isDeleting && (
                    <MaterialIcon
                      name="progress_activity"
                      size={14}
                      className="animate-spin"
                    />
                  )}
                  Yes, delete product
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setConfirmDelete(false)}
                  disabled={isDeleting}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="border-destructive/30 text-destructive hover:bg-destructive/10 hover:text-destructive"
                onClick={() => setConfirmDelete(true)}
                disabled={isPending || isDeleting}
              >
                Delete product
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
