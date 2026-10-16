import type { Metadata } from "next";
import { requireOrg } from "@/lib/auth/guards";
import { AppShell } from "@/components/shell/app-shell";
import { TokensContent } from "@/components/settings/tokens-content";

export const metadata: Metadata = {
  title: "API Tokens — Settings — Kova",
  description: "Generate and manage scoped API tokens for CI integrations and automation.",
};

export default async function TokensPage() {
  const { user, organization } = await requireOrg("/settings/tokens");

  return (
    <AppShell user={user} organizationName={organization.name}>
      <TokensContent />
    </AppShell>
  );
}
