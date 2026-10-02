import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { requireOrg } from "@/lib/auth/guards";
import { getAccessToken } from "@/lib/auth/server";
import { AppShell } from "@/components/shell/app-shell";
import { getMission, getMissionExecutions } from "@/lib/api/missions";
import { MissionDetail } from "@/components/flows/mission-detail";

interface PageProps {
  params: Promise<{ flowId: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { flowId } = await params;
  const token = await getAccessToken();
  const mission = await getMission(flowId, token ?? undefined);
  return {
    title: mission ? `${mission.name} — Kova` : "Mission — Kova",
    description: mission?.objective || "Kova mission details and journey execution.",
  };
}

export default async function FlowDetailPage({ params }: PageProps) {
  const { flowId } = await params;
  const { session, user, organization } = await requireOrg(`/flows/${flowId}`);
  const token = (await getAccessToken()) ?? session.access_token;

  const mission = await getMission(flowId, token);
  if (!mission) {
    notFound();
  }

  const executions = await getMissionExecutions(mission.id, token);

  return (
    <AppShell user={user} organizationName={organization.name}>
      <div className="w-full max-w-5xl mx-auto px-6 py-10 md:py-14 animate-in fade-in duration-300">
        <MissionDetail
          mission={mission}
          executions={executions}
        />
      </div>
    </AppShell>
  );
}
