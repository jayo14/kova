import type { Metadata } from "next";
import Link from "next/link";
import { requireOrg } from "@/lib/auth/guards";
import { getAccessToken } from "@/lib/auth/server";
import { AppShell } from "@/components/shell/app-shell";
import { MaterialIcon } from "@/components/shared/material-icon";
import { buttonVariants } from "@/components/ui/button";
import { getProjects } from "@/lib/api/projects";
import { getMissions, getMissionExecutions } from "@/lib/api/missions";
import { ProjectList } from "@/components/projects";
import { cn } from "@/lib/utils";
import type { ProjectSummary } from "@/lib/types";

export const metadata: Metadata = {
  title: "Products — Kova",
  description: "Products and applications Kova is configured to test and operate.",
};

export default async function ProjectsPage() {
  const { session, user, organization } = await requireOrg("/projects");
  const token = (await getAccessToken()) ?? session.access_token;

  const projects = await getProjects(token).catch(() => []);

  const summaries: ProjectSummary[] = await Promise.all(
    projects.map(async (p) => {
      try {
        const missions = await getMissions(p.id, token);
        let executionCount = 0;
        const execPromises = missions.map(async (m) => {
          try {
            const execs = await getMissionExecutions(m.id, token);
            return execs.length;
          } catch {
            return 0;
          }
        });
        const counts = await Promise.all(execPromises);
        executionCount = counts.reduce((acc, count) => acc + count, 0);

        return {
          ...p,
          missionCount: missions.length,
          executionCount,
        };
      } catch {
        return {
          ...p,
          missionCount: 0,
          executionCount: 0,
        };
      }
    })
  );

  return (
    <AppShell user={user} organizationName={organization.name}>
      <div className="w-full max-w-5xl mx-auto px-6 py-10 md:py-14 animate-in fade-in duration-300">
        <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-display sm:text-[2.25rem] font-bold text-foreground mb-1.5 tracking-tight">
              Products
            </h1>
            <p className="text-body-sm text-muted-foreground leading-relaxed">
              Software products and applications Kova understands and operates.
            </p>
          </div>

          <Link
            href="/explore"
            className={cn(
              buttonVariants({ variant: "default" }),
              "inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-body-sm font-medium shadow-sm shrink-0"
            )}
          >
            <span>Give Kova a product</span>
            <MaterialIcon name="arrow_forward" size={16} />
          </Link>
        </div>

        <ProjectList projects={summaries} />
      </div>
    </AppShell>
  );
}
