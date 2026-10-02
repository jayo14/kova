"use client";

import type { Credential } from "@/lib/types";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface CredentialRowProps {
  credential: Credential;
  onEdit: (credential: Credential) => void;
  onDelete: (credential: Credential) => void;
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "Never";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  return `${days}d ago`;
}

export function CredentialRow({
  credential,
  onEdit,
  onDelete,
}: CredentialRowProps) {
  return (
    <div className="group rounded-xl border border-border/70 bg-card/50 transition-colors hover:bg-card/90 hover:border-border">
      {/* Desktop layout */}
      <div className="hidden md:grid md:grid-cols-12 md:items-center md:gap-4 px-4 py-3.5">
        {/* Name */}
        <div className="col-span-3 min-w-0 flex items-center gap-2">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-secondary/70 text-secondary-foreground">
            <MaterialIcon name="key" size={14} />
          </div>
          <span className="text-body-sm font-medium text-foreground truncate">
            {credential.name}
          </span>
        </div>

        {/* Account / Email */}
        <div className="col-span-3 min-w-0">
          <span className="text-body-sm text-muted-foreground truncate block font-mono text-[13px]">
            {credential.email}
          </span>
        </div>

        {/* Role */}
        <div className="col-span-2 min-w-0">
          {credential.role ? (
            <Badge variant="secondary" className="text-caption font-normal">
              {credential.role}
            </Badge>
          ) : (
            <span className="text-caption text-muted-foreground/60">—</span>
          )}
        </div>

        {/* Project */}
        <div className="col-span-2 min-w-0">
          {credential.projectName ? (
            <span className="text-body-xs text-muted-foreground truncate block">
              {credential.projectName}
            </span>
          ) : (
            <span className="text-caption text-muted-foreground/60">—</span>
          )}
        </div>

        {/* Last used */}
        <div className="col-span-1 min-w-0 text-right">
          <span className="text-caption text-muted-foreground whitespace-nowrap">
            {relativeTime(credential.lastUsedAt)}
          </span>
        </div>

        {/* Actions */}
        <div className="col-span-1 flex justify-end">
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Actions for ${credential.name}`}
                  className="opacity-70 group-hover:opacity-100"
                />
              }
            >
              <MaterialIcon name="more_horiz" size={18} />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => onEdit(credential)}>
                <MaterialIcon name="edit" size={16} />
                Edit
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => onDelete(credential)}
                className="text-destructive focus:text-destructive"
              >
                <MaterialIcon name="delete" size={16} />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Mobile stacked layout */}
      <div className="flex flex-col gap-2 p-3.5 md:hidden">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-secondary/70 text-secondary-foreground">
              <MaterialIcon name="key" size={12} />
            </div>
            <span className="text-body-sm font-medium text-foreground truncate">
              {credential.name}
            </span>
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Actions for ${credential.name}`}
                />
              }
            >
              <MaterialIcon name="more_horiz" size={18} />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => onEdit(credential)}>
                <MaterialIcon name="edit" size={16} />
                Edit
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => onDelete(credential)}
                className="text-destructive focus:text-destructive"
              >
                <MaterialIcon name="delete" size={16} />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <div className="text-body-xs text-muted-foreground font-mono text-[12px] truncate">
          {credential.email}
        </div>

        <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-border/40 text-caption text-muted-foreground">
          {credential.role && (
            <Badge variant="secondary" className="text-caption font-normal">
              {credential.role}
            </Badge>
          )}
          {credential.projectName && (
            <span className="truncate">{credential.projectName}</span>
          )}
          <span className="ml-auto text-caption text-muted-foreground/80">
            Used {relativeTime(credential.lastUsedAt)}
          </span>
        </div>
      </div>
    </div>
  );
}
