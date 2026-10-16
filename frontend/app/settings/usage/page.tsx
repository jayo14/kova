import type { Metadata } from "next";
import { requireOrg } from "@/lib/auth/guards";
import { AppShell } from "@/components/shell/app-shell";
import { UsageContent } from "@/components/settings/usage-content";

export const metadata: Metadata = {
  title: "Usage & Quotas — Settings — Kova",
  description: "Monitor execution usage, evidence storage, and subscription limits.",
};

export default async function UsagePage() {
  const { user, organization } = await requireOrg("/settings/usage");

  return (
    <AppShell user={user} organizationName={organization.name}>
      <UsageContent />
    </AppShell>
  );
}
