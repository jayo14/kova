import type { Metadata } from "next";
import { requireOrg } from "@/lib/auth/guards";
import { AppShell } from "@/components/shell/app-shell";
import { BillingContent } from "@/components/billing/billing-content";

export const metadata: Metadata = {
  title: "Billing & Plans — Kova",
  description: "Manage subscription plans, usage metering, and billing invoices.",
};

export default async function BillingPage() {
  const { user, organization } = await requireOrg("/billing");

  return (
    <AppShell user={user} organizationName={organization.name}>
      <BillingContent user={user} organizationName={organization.name} />
    </AppShell>
  );
}
