"use client";

import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";

interface CredentialEmptyStateProps {
  onAdd: () => void;
}

export function CredentialEmptyState({ onAdd }: CredentialEmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border/80 bg-card/30 px-6 py-16 text-center sm:py-20">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-secondary/80 text-foreground shadow-xs">
        <MaterialIcon
          name="key"
          size={24}
          className="text-primary"
        />
      </div>
      <h2 className="text-h3 font-medium tracking-tight text-foreground mb-2">
        No test accounts yet
      </h2>
      <p className="text-body-sm text-muted-foreground mb-2 max-w-md leading-relaxed">
        Add an account Kova can use when a mission requires authentication.
      </p>
      <div className="mb-6 flex items-center gap-1.5 text-caption text-muted-foreground/80">
        <MaterialIcon name="lock" size={13} className="shrink-0 text-muted-foreground" />
        <span>Passwords are stored securely and are never shown after saving.</span>
      </div>
      <Button onClick={onAdd} className="gap-2">
        <MaterialIcon name="add" size={16} />
        Add test account
      </Button>
    </div>
  );
}
