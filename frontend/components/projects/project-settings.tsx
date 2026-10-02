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

    startTransition(async () => {
      const updated = await updateProject(project.id, {
        name: trimmedName,
        baseUrl: trimmedUrl,
        description: description.trim() || undefined,
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
