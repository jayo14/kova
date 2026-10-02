"use client";

import type { OrganizationMember } from "@/lib/types";
import { memberRoleLabels } from "@/lib/types";
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

interface MemberRowProps {
  member: OrganizationMember;
  onChangeRole: (member: OrganizationMember) => void;
  onRemove: (member: OrganizationMember) => void;
  canManage: boolean;
}

export function MemberRow({
  member,
  onChangeRole,
  onRemove,
  canManage,
}: MemberRowProps) {
  const isOwner = member.role === "owner";
  const isSelf = member.isCurrentUser;
  const hasActions = canManage && !isOwner && !isSelf;

  return (
    <div className="group rounded-xl border border-border/70 bg-card/50 transition-colors hover:bg-card/90 hover:border-border">
      {/* Desktop layout */}
      <div className="hidden md:grid md:grid-cols-12 md:items-center md:gap-4 px-4 py-3.5">
        {/* Name */}
        <div className="col-span-4 min-w-0 flex items-center gap-2.5">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-secondary/70 text-secondary-foreground">
            <MaterialIcon name="person" size={15} />
          </div>
          <span className="text-body-sm font-medium text-foreground truncate">
            {member.name}
          </span>
          {isSelf && (
            <span className="inline-flex items-center rounded-md bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary shrink-0">
              You
            </span>
          )}
        </div>

        {/* Email */}
        <div className="col-span-4 min-w-0">
          <span className="text-body-sm text-muted-foreground truncate block font-mono text-[13px]">
            {member.email}
          </span>
        </div>

        {/* Role */}
        <div className="col-span-3 min-w-0">
          <Badge
            variant={isOwner ? "default" : "secondary"}
            className="text-caption font-normal"
          >
            {memberRoleLabels[member.role] || member.role}
          </Badge>
        </div>

        {/* Actions */}
        <div className="col-span-1 flex justify-end">
          {hasActions ? (
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Actions for ${member.name}`}
                    className="opacity-70 group-hover:opacity-100"
                  />
                }
              >
                <MaterialIcon name="more_horiz" size={18} />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => onChangeRole(member)}>
                  <MaterialIcon name="swap_horiz" size={16} />
                  Change role
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => onRemove(member)}
                  className="text-destructive focus:text-destructive"
                >
                  <MaterialIcon name="person_remove" size={16} />
                  Remove member
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <span className="w-7" />
          )}
        </div>
      </div>

      {/* Mobile stacked layout */}
      <div className="flex flex-col gap-2 p-3.5 md:hidden">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-secondary/70 text-secondary-foreground">
              <MaterialIcon name="person" size={13} />
            </div>
            <span className="text-body-sm font-medium text-foreground truncate">
              {member.name}
            </span>
            {isSelf && (
              <span className="inline-flex items-center rounded-md bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary shrink-0">
                You
              </span>
            )}
          </div>

          {hasActions && (
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Actions for ${member.name}`}
                  />
                }
              >
                <MaterialIcon name="more_horiz" size={18} />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => onChangeRole(member)}>
                  <MaterialIcon name="swap_horiz" size={16} />
                  Change role
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => onRemove(member)}
                  className="text-destructive focus:text-destructive"
                >
                  <MaterialIcon name="person_remove" size={16} />
                  Remove member
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>

        <div className="text-body-xs text-muted-foreground font-mono text-[12px] truncate">
          {member.email}
        </div>

        <div className="flex items-center pt-1 border-t border-border/40">
          <Badge
            variant={isOwner ? "default" : "secondary"}
            className="text-caption font-normal"
          >
            {memberRoleLabels[member.role] || member.role}
          </Badge>
        </div>
      </div>
    </div>
  );
}
