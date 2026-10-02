import type { Metadata } from "next";
import Link from "next/link";
import { requireOrg } from "@/lib/auth/guards";
import { getAccessToken } from "@/lib/auth/server";
import { AppShell } from "@/components/shell/app-shell";
import { MaterialIcon } from "@/components/shared/material-icon";
import { buttonVariants } from "@/components/ui/button";
import { getMissions, getMissionExecutions } from "@/lib/api/missions";
import { getProjects } from "@/lib/api/projects";
import { MissionList } from "@/components/flows";
import { cn } from "@/lib/utils";
import type { MissionExecution } from "@/lib/types";

export const metadata: Metadata = {
  title: "Missions — Kova",
  description: "Things you've asked Kova to accomplish.",
};

interface FlowsPageProps {
  searchParams?: Promise<{
    projectId?: string;
    project?: string;
  }>;
}

export default async function FlowsPage({ searchParams }: FlowsPageProps) {
  const { session, user, organization } = await requireOrg("/flows");
  const token = (await getAccessToken()) ?? session.access_token;

  const resolvedParams = searchParams ? await searchParams : undefined;
  const initialProjectId = resolvedParams?.projectId || resolvedParams?.project;

  const [missions, projects] = await Promise.all([
    getMissions(undefined, token).catch(() => []),
    getProjects(token).catch(() => []),
  ]);

  const executionMap = new Map<string, MissionExecution>();
  const executionCounts = new Map<string, number>();

  await Promise.all(
    missions.map(async (m) => {
      try {
        const execs = await getMissionExecutions(m.id, token);
        if (execs.length > 0) {
          executionMap.set(m.id, execs[0]);
          executionCounts.set(m.id, execs.length);
        }
      } catch {
        // ignore
      }
    })
  );

  const giveJobHref = initialProjectId
    ? `/explore?projectId=${initialProjectId}`
    : "/explore";

  return (
    <AppShell user={user} organizationName={organization.name}>
      <div className="w-full max-w-5xl mx-auto px-6 py-10 md:py-14 animate-in fade-in duration-300">
        <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-display sm:text-[2.25rem] font-bold text-foreground mb-1.5 tracking-tight">
              Missions
            </h1>
            <p className="text-body-sm text-muted-foreground leading-relaxed">
              Things you&apos;ve asked Kova to accomplish.
            </p>
          </div>

          <Link
            href={giveJobHref}
            className={cn(
              buttonVariants({ variant: "default" }),
              "inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-body-sm font-medium shadow-sm shrink-0"
            )}
          >
            <span>+ Give Kova a job</span>
            <MaterialIcon name="arrow_forward" size={16} />
          </Link>
        </div>

        <MissionList
          missions={missions}
          executions={executionMap}
          executionCounts={executionCounts}
          initialProjectId={initialProjectId}
          projects={projects.map((p) => ({ id: p.id, name: p.name }))}
        />
      </div>
    </AppShell>
  );
}
