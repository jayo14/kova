import { getProjects } from "./projects";
import { getMissions } from "./missions";
import { getExecutions } from "./executions";
import type { ProjectSummary, ExecutionDetail } from "@/lib/types";

export interface DashboardData {
  projects: ProjectSummary[];
  recentExecutions: ExecutionDetail[];
  hasWork: boolean;
}

/**
 * Server-side data fetcher for the authenticated command center dashboard.
 * Queries real projects and recent executions from the backend,
 * or gracefully returns an empty intentional state if none exist.
 */
export async function getDashboardData(token?: string): Promise<DashboardData> {
  try {
    const rawProjects = await getProjects(token);

    // Fetch missions for each project in parallel
    const projectsWithCounts: ProjectSummary[] = await Promise.all(
      rawProjects.map(async (project) => {
        try {
          const missions = await getMissions(project.id, token);
          return {
            ...project,
            missionCount: missions.length,
          };
        } catch {
          return {
            ...project,
            missionCount: 0,
          };
        }
      })
    );

    let recentExecutions: ExecutionDetail[] = [];
    try {
      const allExecutions = await getExecutions(undefined, token);
      recentExecutions = allExecutions.slice(0, 5);
    } catch {
      recentExecutions = [];
    }

    const hasWork = projectsWithCounts.length > 0 || recentExecutions.length > 0;

    return {
      projects: projectsWithCounts,
      recentExecutions,
      hasWork,
    };
  } catch {
    // If backend is unreachable or offline, return clean empty workspace
    return {
      projects: [],
      recentExecutions: [],
      hasWork: false,
    };
  }
}
