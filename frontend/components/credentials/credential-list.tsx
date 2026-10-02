"use client";

import type { Credential } from "@/lib/types";
import { CredentialRow } from "./credential-row";
import { CredentialEmptyState } from "./credential-empty-state";
import { useState } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";

import { Button } from "@/components/ui/button";

interface CredentialListProps {
  credentials: Credential[];
  onAdd: () => void;
  onEdit: (credential: Credential) => void;
  onDelete: (credential: Credential) => void;
}

export function CredentialList({
  credentials,
  onAdd,
  onEdit,
  onDelete,
}: CredentialListProps) {
  const [search, setSearch] = useState("");

  const filtered = credentials.filter((c) => {
    if (!search.trim()) return true;
    const q = search.trim().toLowerCase();
    return (
      c.name.toLowerCase().includes(q) ||
      c.email.toLowerCase().includes(q) ||
      (c.role?.toLowerCase().includes(q) ?? false) ||
      (c.projectName?.toLowerCase().includes(q) ?? false)
    );
  });

  if (credentials.length === 0) {
    return <CredentialEmptyState onAdd={onAdd} />;
  }

  return (
    <div className="space-y-4">
      {/* Search Bar */}
      <div className="relative">
        <MaterialIcon
          name="search"
          size={18}
          className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
        />
        <input
          type="text"
          placeholder="Search test accounts by name, email, role, or product..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full h-10 rounded-xl border border-border/80 bg-card/60 pl-10 pr-9 text-body-sm text-foreground placeholder:text-muted-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20 transition-colors"
          aria-label="Search test accounts"
        />
        {search && (
          <button
            type="button"
            onClick={() => setSearch("")}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground p-0.5 rounded-md transition-colors"
            aria-label="Clear search"
          >
            <MaterialIcon name="close" size={16} />
          </button>
        )}
      </div>

      {/* Desktop Column Headers */}
      {filtered.length > 0 && (
        <div className="hidden md:grid md:grid-cols-12 md:items-center md:gap-4 px-4 py-2 text-caption font-medium uppercase tracking-wider text-muted-foreground/70">
          <div className="col-span-3">Name</div>
          <div className="col-span-3">Account</div>
          <div className="col-span-2">Role</div>
          <div className="col-span-2">Product</div>
          <div className="col-span-1 text-right">Last used</div>
          <div className="col-span-1 text-right">Actions</div>
        </div>
      )}

      {/* Empty Filter State */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border/70 bg-card/20 py-12 px-4 text-center">
          <MaterialIcon
            name="search_off"
            size={32}
            className="mb-3 text-muted-foreground/40"
          />
          <p className="text-body-sm font-medium text-foreground mb-1">
            No test accounts match &ldquo;{search}&rdquo;
          </p>
          <p className="text-caption text-muted-foreground mb-4">
            Try adjusting your search terms or clear the filter.
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSearch("")}
          >
            Clear search
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {filtered.map((cred) => (
            <CredentialRow
              key={cred.id}
              credential={cred}
              onEdit={onEdit}
              onDelete={onDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}
