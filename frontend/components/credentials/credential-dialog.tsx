"use client";

import type { Credential, CreateCredentialInput, UpdateCredentialInput } from "@/lib/types";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { CredentialForm } from "./credential-form";

interface CredentialDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  credential?: Credential | null;
  projects?: Array<{ id: string; name: string }>;
  initialProjectId?: string;
  onSubmit: (input: CreateCredentialInput | UpdateCredentialInput) => void;
  loading?: boolean;
  error?: string | null;
}

export function CredentialDialog({
  open,
  onOpenChange,
  credential,
  projects = [],
  initialProjectId,
  onSubmit,
  loading = false,
  error = null,
}: CredentialDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {credential ? "Edit test account" : "Add test account"}
          </DialogTitle>
          <DialogDescription>
            {credential
              ? "Update the account details below."
              : "Add an account Kova can use when it needs to sign in."}
          </DialogDescription>
        </DialogHeader>
        <CredentialForm
          key={credential?.id ?? "new"}
          credential={credential}
          projects={projects}
          initialProjectId={initialProjectId}
          onSubmit={onSubmit}
          onCancel={() => onOpenChange(false)}
          loading={loading}
          error={error}
        />
      </DialogContent>
    </Dialog>
  );
}
