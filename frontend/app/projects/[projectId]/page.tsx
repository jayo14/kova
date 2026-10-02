import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { requireOrg } from "@/lib/auth/guards";
import { getAccessToken } from "@/lib/auth/server";
import { AppShell } from "@/components/shell/app-shell";
import { getProject } from "@/lib/api/projects";
import { getMissions, getMissionExecutions } from "@/lib/api/missions";
import { getExecutions } from "@/lib/api/executions";
import {
  ProjectHeader,
  ProjectOverview,
  ProjectMissions,
  ProjectActivity,
  ProjectCommandInput,
} from "@/components/projects";
import type { ProjectActivity as Activity, Mission, ExecutionDetail, MissionExecution } from "@/lib/types";

interface PageProps {
  params: Promise<{ projectId: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { projectId } = await params;
  const token = await getAccessToken();
  const project = await getProject(projectId, token ?? undefined);
  return {
    title: project ? `${project.name} — Kova` : "Product — Kova",
  };
}

function buildActivities(
  missions: Mission[],
  executions: ExecutionDetail[]
): Activity[] {
  const activities: Activity[] = [];

  for (const ex of executions) {
    const mission = missions.find((m) => m.id === ex.missionId);
    const missionTitle = mission ? mission.name : "Mission";

    if (ex.status === "completed") {
      activities.push({
        id: `ex-${ex.id}`,
        type: "execution_completed",
        title: `Mission: ${missionTitle} completed`,
        createdAt: ex.completedAt ?? ex.createdAt,
        executionId: ex.id,
        missionId: ex.missionId,
      });
    } else if (ex.status === "failed") {
      activities.push({
        id: `ex-${ex.id}`,
        type: "execution_failed",
        title: `Mission: ${missionTitle} failed`,
        description: ex.error ?? undefined,
        createdAt: ex.completedAt ?? ex.createdAt,
        executionId: ex.id,
        missionId: ex.missionId,
      });
    }
  }

  for (const m of missions) {
    activities.push({
      id: `m-${m.id}`,
      type: "mission_created",
      title: `Mission mapped: ${m.name}`,
      description: m.objective,
      createdAt: m.createdAt,
      missionId: m.id,
    });
  }

  return activities
    .sort(
      (a, b) =>
        new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
    )
    .slice(0, 10);
}

export default async function ProjectDetailPage({ params }: PageProps) {
  const { projectId } = await params;
  const { session, user, organization } = await requireOrg(`/projects/${projectId}`);
  const token = (await getAccessToken()) ?? session.access_token;

  const project = await getProject(projectId, token);
  if (!project) notFound();

  const [missions, executions] = await Promise.all([
    getMissions(projectId, token).catch(() => []),
    getExecutions({ projectId: project.id }, token).catch(() => []),
  ]);

  const executionMap = new Map<string, MissionExecution>();
  await Promise.all(
    missions.map(async (m) => {
      try {
        const execs = await getMissionExecutions(m.id, token);
        if (execs.length > 0) {
          executionMap.set(m.id, execs[0]);
        }
      } catch {
        // ignore
      }
    })
  );

  const activities = buildActivities(missions, executions);

  return (
    <AppShell user={user} organizationName={organization.name}>
      <div className="w-full max-w-5xl mx-auto px-6 py-10 md:py-14 animate-in fade-in duration-300">
        <ProjectHeader
          project={project}
          missionCount={missions.length}
        />

        <div className="space-y-8">
          <div className="rounded-2xl border border-border/80 bg-card/60 p-6 shadow-xs">
            <ProjectCommandInput
              projectName={project.name}
              projectId={project.id}
              baseUrl={project.baseUrl}
            />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <div className="space-y-6 lg:col-span-2">
              <ProjectOverview project={project} />
              <ProjectMissions
                missions={missions}
                executions={executionMap}
                projectId={project.id}
                baseUrl={project.baseUrl}
              />
            </div>

            <div>
              <ProjectActivity activities={activities} />
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
