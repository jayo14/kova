import type { Metadata } from "next";
import { requireOrg } from "@/lib/auth/guards";
import { AppShell } from "@/components/shell/app-shell";
import { SettingsContent } from "@/components/settings/settings-content";

export const metadata: Metadata = {
  title: "Settings — Kova",
  description: "Manage your Kova account and preferences.",
};

export default async function SettingsPage() {
  const { user, organization } = await requireOrg("/settings");

  return (
    <AppShell user={user} organizationName={organization.name}>
      <SettingsContent user={user} />
    </AppShell>
  );
}
