import type { Organization, OrganizationMember } from "@/lib/types";

let currentOrganization: Organization = {
  id: "org-default",
  name: "Default Workspace",
  slug: "default-workspace",
  createdAt: new Date().toISOString(),
};

const userOrganizations = new Map<string, Organization>();
const userMemberships = new Map<string, OrganizationMember>();

/**
 * Generate a friendly workspace name from user's full name or email prefix.
 */
export function generateDefaultWorkspaceName(name?: string, email?: string): string {
  if (name && name.trim()) {
    const firstName = name.trim().split(" ")[0];
    return `${firstName}'s Workspace`;
  }
  if (email && email.includes("@")) {
    const local = email.split("@")[0];
    const capitalized = local.charAt(0).toUpperCase() + local.slice(1);
    return `${capitalized}'s Workspace`;
  }
  return "My Workspace";
}

/**
 * Resolve or automatically provision an organization for an authenticated user.
 */
export function resolveUserOrganization(user: {
  id: string;
  email?: string;
  user_metadata?: { name?: string };
}): Organization {
  const existing = userOrganizations.get(user.id);
  if (existing) {
    currentOrganization = existing;
    return existing;
  }

  const workspaceName = generateDefaultWorkspaceName(
    user.user_metadata?.name,
    user.email
  );
  const slug = workspaceName.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");

  const newOrg: Organization = {
    id: `org-${user.id.slice(0, 8)}`,
    name: workspaceName,
    slug,
    createdAt: new Date().toISOString(),
  };

  const newMembership: OrganizationMember = {
    id: `mem-${user.id.slice(0, 8)}`,
    organizationId: newOrg.id,
    userId: user.id,
    name: user.user_metadata?.name || user.email?.split("@")[0] || "Owner",
    email: user.email || "user@example.com",
    role: "owner",
    isCurrentUser: true,
    createdAt: newOrg.createdAt,
  };

  userOrganizations.set(user.id, newOrg);
  userMemberships.set(user.id, newMembership);
  currentOrganization = newOrg;

  return newOrg;
}

export function getActiveOrganization(): Organization {
  return currentOrganization;
}

export function setActiveOrganization(org: Organization): void {
  currentOrganization = org;
}
