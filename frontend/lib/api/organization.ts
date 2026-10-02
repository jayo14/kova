import type {
  Organization,
  OrganizationMember,
  OrganizationInvitation,
  UpdateOrganizationInput,
  InviteMemberInput,
  UpdateMemberRoleInput,
} from "@/lib/types";

import {
  getActiveOrganization,
  setActiveOrganization,
} from "@/lib/auth/organization";

// ── In-memory store (client-side workspace state) ────────────

const members = new Map<string, OrganizationMember>();
const invitations = new Map<string, OrganizationInvitation>();
let nextInvitationId = 1;

export function initOrganization(
  org: Organization,
  currentUserName?: string,
  currentUserEmail?: string,
  currentUserId?: string
): void {
  setActiveOrganization(org);

  const existingCurrent = Array.from(members.values()).find((m) => m.isCurrentUser);
  if (!existingCurrent) {
    const now = org.createdAt || new Date().toISOString();
    const ownerMember: OrganizationMember = {
      id: `mem-${(currentUserId || "current").slice(0, 8)}`,
      organizationId: org.id,
      userId: currentUserId || "user-current",
      name: currentUserName || currentUserEmail?.split("@")[0] || "Owner",
      email: currentUserEmail || "user@example.com",
      role: "owner",
      isCurrentUser: true,
      createdAt: now,
    };
    members.set(ownerMember.id, ownerMember);
  } else if (currentUserName || currentUserEmail) {
    existingCurrent.name = currentUserName || existingCurrent.name;
    existingCurrent.email = currentUserEmail || existingCurrent.email;
    existingCurrent.organizationId = org.id;
  }
}

function seedIfNeeded(): void {
  if (members.size > 0) return;

  const org = getActiveOrganization();
  const now = new Date().toISOString();
  const seedMembers: OrganizationMember[] = [
    {
      id: "mem-owner",
      organizationId: org.id,
      userId: "user-owner",
      name: "Owner",
      email: "owner@example.com",
      role: "owner",
      isCurrentUser: true,
      createdAt: now,
    },
  ];

  for (const m of seedMembers) {
    members.set(m.id, m);
  }
}

// ── Error Mapping ──────────────────────────────────────────

export function mapOrganizationError(err: unknown, fallback: string): string {
  const msg = err instanceof Error ? err.message : String(err);
  if (msg === "already_member") return "This person is already a member.";
  if (msg === "already_pending") return "An invitation is already pending for this email.";
  if (msg === "invalid_email") return "Enter a valid email address.";
  if (msg === "unauthorized") return "You don't have permission to do that.";
  if (msg === "owner_protected") return "The workspace owner cannot be modified or removed.";
  return fallback;
}

// ── Public API ─────────────────────────────────────────────

export function getOrganization(): Organization {
  return getActiveOrganization();
}

export function updateOrganization(
  input: UpdateOrganizationInput
): Organization {
  const current = getActiveOrganization();
  const updated: Organization = {
    ...current,
    ...(input.name ? { name: input.name.trim() } : {}),
    updatedAt: new Date().toISOString(),
  };
  setActiveOrganization(updated);
  return updated;
}

export function getMembers(): OrganizationMember[] {
  seedIfNeeded();
  return Array.from(members.values()).sort((a, b) => {
    if (a.role === "owner") return -1;
    if (b.role === "owner") return 1;
    return a.name.localeCompare(b.name);
  });
}

export function getInvitations(): OrganizationInvitation[] {
  return Array.from(invitations.values()).sort(
    (a, b) =>
      new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  );
}

export function inviteMember(
  input: InviteMemberInput
): OrganizationMember {
  const cleanEmail = input.email.trim().toLowerCase();
  if (!cleanEmail || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
    throw new Error("invalid_email");
  }

  // Check for duplicate email
  for (const m of members.values()) {
    if (m.email.toLowerCase() === cleanEmail) {
      throw new Error("already_member");
    }
  }

  const id = `mem-${nextInvitationId++}`;
  const now = new Date().toISOString();
  const newMember: OrganizationMember = {
    id,
    organizationId: getActiveOrganization().id,
    userId: `user-${cleanEmail.replace(/[^a-z0-9]/gi, "")}`,
    name: cleanEmail.split("@")[0],
    email: cleanEmail,
    role: input.role,
    isCurrentUser: false,
    createdAt: now,
  };
  members.set(id, newMember);
  return newMember;
}

export function updateMemberRole(
  input: UpdateMemberRoleInput
): OrganizationMember | null {
  const member = members.get(input.memberId);
  if (!member) return null;
  if (member.role === "owner") {
    throw new Error("owner_protected");
  }
  const updated: OrganizationMember = { ...member, role: input.role };
  members.set(input.memberId, updated);
  return updated;
}

export function removeMember(memberId: string): boolean {
  const member = members.get(memberId);
  if (!member) return false;
  if (member.role === "owner") {
    throw new Error("owner_protected");
  }
  if (member.isCurrentUser) {
    throw new Error("unauthorized");
  }
  return members.delete(memberId);
}

export function cancelInvitation(invitationId: string): boolean {
  const inv = invitations.get(invitationId);
  if (!inv) return false;
  if (inv.status !== "pending") return false;
  invitations.delete(invitationId);
  return true;
}

export function resendInvitation(
  invitationId: string
): OrganizationInvitation | null {
  const inv = invitations.get(invitationId);
  if (!inv) return null;
  if (inv.status !== "pending") return null;
  const updated: OrganizationInvitation = {
    ...inv,
    expiresAt: new Date(Date.now() + 7 * 86400000).toISOString(),
  };
  invitations.set(invitationId, updated);
  return updated;
}
