"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import type {
  Credential,
  CreateCredentialInput,
  UpdateCredentialInput,
} from "@/lib/types";
import {
  getCredentials,
  createCredential,
  updateCredential,
  deleteCredential,
} from "@/lib/api/credentials";
import { CredentialList } from "@/components/credentials/credential-list";
import { CredentialDialog } from "@/components/credentials/credential-dialog";
import { DeleteCredentialDialog } from "@/components/credentials/delete-credential-dialog";
import { Button } from "@/components/ui/button";
import { MaterialIcon } from "@/components/shared/material-icon";

interface CredentialsContentProps {
  initialCredentials?: Credential[];
  projects?: Array<{ id: string; name: string }>;
  initialProjectId?: string;
}

export function CredentialsContent({
  initialCredentials = [],
  projects = [],
  initialProjectId,
}: CredentialsContentProps) {
  const [credentials, setCredentials] = useState<Credential[]>(initialCredentials);
  const [addOpen, setAddOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Credential | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Credential | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  const loadCredentials = useCallback(async () => {
    try {
      const list = await getCredentials();
      if (mountedRef.current) setCredentials(list);
    } catch {
      // Keep existing list on failure
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const handleCreate = useCallback(
    async (input: CreateCredentialInput | UpdateCredentialInput) => {
      setLoading(true);
      setError(null);
      try {
        await createCredential(input as CreateCredentialInput);
        await loadCredentials();
        setAddOpen(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : "We couldn't save the test account. Try again.");
      } finally {
        setLoading(false);
      }
    },
    [loadCredentials]
  );

  const handleUpdate = useCallback(
    async (input: CreateCredentialInput | UpdateCredentialInput) => {
      if (!editTarget) return;
      setLoading(true);
      setError(null);
      try {
        const updated = await updateCredential(editTarget.id, input);
        if (updated) {
          await loadCredentials();
          setEditTarget(null);
        } else {
          setError("Account not found. It may have been removed.");
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "We couldn't update the test account. Try again.");
      } finally {
        setLoading(false);
      }
    },
    [editTarget, loadCredentials]
  );

  const handleDelete = useCallback(async () => {
    if (!deleteTarget) return;
    setLoading(true);
    setDeleteError(null);
    try {
      const ok = await deleteCredential(deleteTarget.id, undefined, deleteTarget.projectId || undefined);
      if (ok) {
        await loadCredentials();
        setDeleteTarget(null);
      }
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Failed to delete test account.");
    } finally {
      setLoading(false);
    }
  }, [deleteTarget, loadCredentials]);

  return (
    <div className="w-full max-w-5xl mx-auto px-6 py-10 md:py-14 animate-in fade-in duration-300">
      <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-display sm:text-[2.25rem] font-bold text-foreground mb-1.5 tracking-tight">
            Credentials
          </h1>
          <p className="text-body-sm text-muted-foreground leading-relaxed">
            Test accounts Kova can use when accessing your applications.
          </p>
        </div>

        <Button
          onClick={() => {
            setError(null);
            setAddOpen(true);
          }}
          className="shrink-0 gap-1.5 rounded-xl shadow-sm"
        >
          <MaterialIcon name="add" size={16} />
          Add test account
        </Button>
      </div>

      <CredentialList
        credentials={credentials}
        onAdd={() => {
          setError(null);
          setAddOpen(true);
        }}
        onEdit={(c) => {
          setError(null);
          setEditTarget(c);
        }}
        onDelete={(c) => {
          setDeleteError(null);
          setDeleteTarget(c);
        }}
      />

      <CredentialDialog
        open={addOpen}
        onOpenChange={(open) => {
          setAddOpen(open);
          if (!open) setError(null);
        }}
        projects={projects}
        initialProjectId={initialProjectId}
        onSubmit={handleCreate}
        loading={loading}
        error={error}
      />

      <CredentialDialog
        open={!!editTarget}
        onOpenChange={(open) => {
          if (!open) {
            setEditTarget(null);
            setError(null);
          }
        }}
        credential={editTarget}
        projects={projects}
        onSubmit={handleUpdate}
        loading={loading}
        error={error}
      />

      <DeleteCredentialDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteTarget(null);
            setDeleteError(null);
          }
        }}
        credential={deleteTarget}
        onConfirm={handleDelete}
        loading={loading}
        error={deleteError}
      />
    </div>
  );
}
