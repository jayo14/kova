"use client";

import { useState, useCallback } from "react";
import type {
  Organization,
  OrganizationMember,
  UpdateOrganizationInput,
  InviteMemberInput,
  UpdateMemberRoleInput,
} from "@/lib/types";
import {
  initOrganization,
  getOrganization,
  updateOrganization,
  getMembers,
  inviteMember,
  updateMemberRole,
  removeMember,
  mapOrganizationError,
} from "@/lib/api/organization";
import { WorkspaceInfo } from "./workspace-info";
import { MemberList } from "./member-list";
import { InviteDialog } from "./invite-dialog";
import { ChangeRoleDialog } from "./change-role-dialog";
import { RemoveMemberDialog } from "./remove-member-dialog";

interface OrganizationContentProps {
  initialOrganization?: Organization;
  user?: {
    id: string;
    email?: string;
    user_metadata?: {
      name?: string;
    };
  };
}

export function OrganizationContent({
  initialOrganization,
  user,
}: OrganizationContentProps) {
  // Initialize organization and owner in workspace state
  if (initialOrganization) {
    initOrganization(
      initialOrganization,
      user?.user_metadata?.name,
      user?.email,
      user?.id
    );
  }

  const [org, setOrg] = useState<Organization>(() =>
    initialOrganization ?? getOrganization()
  );
  const [members, setMembers] = useState<OrganizationMember[]>(() =>
    getMembers()
  );
  const [inviteOpen, setInviteOpen] = useState(false);
  const [changeRoleTarget, setChangeRoleTarget] =
    useState<OrganizationMember | null>(null);
  const [removeTarget, setRemoveTarget] = useState<OrganizationMember | null>(
    null
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  const refreshMembers = useCallback(() => {
    setMembers(getMembers());
  }, []);

  const currentMember = members.find(
    (m) => m.isCurrentUser || (user?.email && m.email.toLowerCase() === user.email.toLowerCase())
  );
  const canManage = currentMember?.role === "owner";

  const handleUpdateOrg = useCallback((input: UpdateOrganizationInput) => {
    setLoading(true);
    try {
      const updated = updateOrganization(input);
      setOrg(updated);
    } catch {
      // keep existing
    } finally {
      setLoading(false);
    }
  }, []);

  const handleInvite = useCallback(
    (input: InviteMemberInput) => {
      setLoading(true);
      setError(null);
      try {
        inviteMember(input);
        setInviteOpen(false);
        refreshMembers();
      } catch (err) {
        setError(mapOrganizationError(err, "We couldn't send the invitation. Try again."));
      } finally {
        setLoading(false);
      }
    },
    [refreshMembers]
  );

  const handleChangeRole = useCallback(
    (input: UpdateMemberRoleInput) => {
      setLoading(true);
      try {
        const updated = updateMemberRole(input);
        if (updated) {
          refreshMembers();
          setChangeRoleTarget(null);
        }
      } catch {
        // keep existing
      } finally {
        setLoading(false);
      }
    },
    [refreshMembers]
  );

  const handleRemove = useCallback(() => {
    if (!removeTarget) return;
    setLoading(true);
    setRemoveError(null);
    try {
      const ok = removeMember(removeTarget.id);
      if (ok) {
        refreshMembers();
        setRemoveTarget(null);
      } else {
        setRemoveError("Failed to remove member. They may no longer be part of this workspace.");
      }
    } catch (err) {
      setRemoveError(mapOrganizationError(err, "We couldn't remove the member. Try again."));
    } finally {
      setLoading(false);
    }
  }, [removeTarget, refreshMembers]);

  return (
    <div className="w-full max-w-5xl mx-auto px-6 py-10 md:py-14 animate-in fade-in duration-300">
      <div className="mb-8">
        <h1 className="text-display sm:text-[2.25rem] font-bold text-foreground mb-1.5 tracking-tight">
          Organization
        </h1>
        <p className="text-body-sm text-muted-foreground leading-relaxed">
          Manage your workspace and the people who can access it.
        </p>
      </div>

      <div className="space-y-8">
        <WorkspaceInfo
          organization={org}
          onUpdate={handleUpdateOrg}
          loading={loading}
          canManage={canManage}
        />

        <MemberList
          members={members}
          onInvite={() => {
            setError(null);
            setInviteOpen(true);
          }}
          onChangeRole={(m) => setChangeRoleTarget(m)}
          onRemove={(m) => {
            setRemoveError(null);
            setRemoveTarget(m);
          }}
          canManage={canManage}
        />
      </div>

      <InviteDialog
        open={inviteOpen}
        onOpenChange={setInviteOpen}
        onInvite={handleInvite}
        loading={loading}
        error={error}
      />

      <ChangeRoleDialog
        open={!!changeRoleTarget}
        onOpenChange={(open) => {
          if (!open) setChangeRoleTarget(null);
        }}
        member={changeRoleTarget}
        onChangeRole={handleChangeRole}
        loading={loading}
      />

      <RemoveMemberDialog
        open={!!removeTarget}
        onOpenChange={(open) => {
          if (!open) {
            setRemoveTarget(null);
            setRemoveError(null);
          }
        }}
        member={removeTarget}
        onConfirm={handleRemove}
        loading={loading}
        error={removeError}
      />
    </div>
  );
}
