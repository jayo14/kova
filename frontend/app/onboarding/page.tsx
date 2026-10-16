import type { Metadata } from "next";
import { requireOrg } from "@/lib/auth/guards";
import { OnboardingWizard } from "@/components/onboarding/wizard";

export const metadata: Metadata = {
  title: "Get Started — Onboarding — Kova",
  description: "Set up your application, credentials, and first continuous validation run in Kova.",
};

export default async function OnboardingPage() {
  const { user } = await requireOrg("/onboarding");

  return (
    <OnboardingWizard
      initialStep={user.user_metadata?.onboarding_step ?? 0}
      userName={user.user_metadata?.name || user.email}
    />
  );
}
