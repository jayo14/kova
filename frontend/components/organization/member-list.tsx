"use client";

import type { OrganizationMember } from "@/lib/types";
import { MemberRow } from "./member-row";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";

interface MemberListProps {
  members: OrganizationMember[];
  onInvite: () => void;
  onChangeRole: (member: OrganizationMember) => void;
  onRemove: (member: OrganizationMember) => void;
  canManage: boolean;
}

export function MemberList({
  members,
  onInvite,
  onChangeRole,
  onRemove,
  canManage,
}: MemberListProps) {
  if (members.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border/80 bg-card/30 px-6 py-14 text-center sm:py-16">
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-secondary/80 text-foreground shadow-xs">
          <MaterialIcon
            name="group"
            size={24}
            className="text-primary"
          />
        </div>
        <h3 className="text-h4 font-medium tracking-tight text-foreground mb-1.5">
          No members yet
        </h3>
        <p className="text-body-sm text-muted-foreground mb-5 max-w-sm leading-relaxed">
          Invite teammates who should have access to this workspace.
        </p>
        {canManage && (
          <Button onClick={onInvite} className="gap-1.5 rounded-xl shadow-sm">
            <MaterialIcon name="person_add" size={16} />
            Invite member
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-body font-semibold text-foreground">Members</h2>
          <p className="text-caption text-muted-foreground">
            {members.length} {members.length === 1 ? "member" : "members"} with access to this workspace
          </p>
        </div>
        {canManage && (
          <Button
            onClick={onInvite}
            size="sm"
            className="gap-1.5 rounded-xl shadow-sm shrink-0"
          >
            <MaterialIcon name="person_add" size={14} />
            Invite member
          </Button>
        )}
      </div>

      {/* Desktop Column Headers */}
      <div className="hidden md:grid md:grid-cols-12 md:items-center md:gap-4 px-4 py-2 text-caption font-medium uppercase tracking-wider text-muted-foreground/70">
        <div className="col-span-4">Name</div>
        <div className="col-span-4">Email</div>
        <div className="col-span-3">Role</div>
        <div className="col-span-1 text-right">Actions</div>
      </div>

      <div className="flex flex-col gap-2">
        {members.map((member) => (
          <MemberRow
            key={member.id}
            member={member}
            onChangeRole={onChangeRole}
            onRemove={onRemove}
            canManage={canManage}
          />
        ))}
      </div>
    </div>
  );
}
