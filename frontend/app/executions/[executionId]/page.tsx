import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { requireOrg } from "@/lib/auth/guards";
import { getAccessToken } from "@/lib/auth/server";
import { AppShell } from "@/components/shell/app-shell";
import { getExecution, getExecutionEvents } from "@/lib/api/executions";
import { mapExecutionEvents } from "@/lib/executions/event-mapper";
import { ExecutionDetailPage } from "@/components/executions/execution-detail-page";

interface PageProps {
  params: Promise<{ executionId: string }>;
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { executionId } = await params;
  const token = await getAccessToken();
  const execution = await getExecution(executionId, token ?? undefined);
  return {
    title: execution ? `${execution.missionName} — Kova` : "Execution — Kova",
    description: execution
      ? `Execution run of ${execution.missionName} on ${execution.projectName}`
      : "Kova execution details and evidence.",
  };
}

export default async function ExecutionPage({ params }: PageProps) {
  const { executionId } = await params;
  const { session, user, organization } = await requireOrg(
    `/executions/${executionId}`
  );
  const token = (await getAccessToken()) ?? session.access_token;

  // Retry fetching execution — may not be committed yet after creation
  let execution = await getExecution(executionId, token);
  if (!execution) {
    await new Promise((r) => setTimeout(r, 1500));
    execution = await getExecution(executionId, token);
  }
  if (!execution) {
    await new Promise((r) => setTimeout(r, 3000));
    execution = await getExecution(executionId, token);
  }
  if (!execution) {
    notFound();
  }

  const events = await getExecutionEvents(executionId, token).catch(() => []);
  const initialActivities = mapExecutionEvents(events);

  return (
    <AppShell user={user} organizationName={organization.name}>
      <div className="w-full max-w-5xl mx-auto px-6 py-10 md:py-14 animate-in fade-in duration-300">
        <ExecutionDetailPage
          initialExecution={execution}
          initialActivities={initialActivities}
          initialEvents={events}
        />
      </div>
    </AppShell>
  );
}
