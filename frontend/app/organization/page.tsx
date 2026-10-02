import type { Metadata } from "next";
import { requireOrg } from "@/lib/auth/guards";
import { AppShell } from "@/components/shell/app-shell";
import { OrganizationContent } from "@/components/organization/organization-content";

export const metadata: Metadata = {
  title: "Organization — Kova",
  description: "Manage your workspace and the people who can access it.",
};

export default async function OrganizationPage() {
  const { user, organization } = await requireOrg("/organization");

  return (
    <AppShell user={user} organizationName={organization.name}>
      <OrganizationContent
        initialOrganization={organization}
        user={user}
      />
    </AppShell>
  );
}
