import { requireOrg } from "@/lib/auth/guards";
import { getAccessToken } from "@/lib/auth/server";
import { AppShell } from "@/components/shell/app-shell";
import { getDashboardData } from "@/lib/api/dashboard";
import {
  DashboardCommandInput,
  RecentExecutions,
  DashboardEmptyState,
} from "@/components/dashboard";
import { ProjectList } from "@/components/projects";

function getGreeting(nameOrEmail?: string): string {
  const hour = new Date().getHours();
  const timeOfDay = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  if (!nameOrEmail) return `${timeOfDay}.`;

  const firstName = nameOrEmail.includes("@")
    ? nameOrEmail.split("@")[0]
    : nameOrEmail.trim().split(" ")[0];

  const capitalized = firstName.charAt(0).toUpperCase() + firstName.slice(1);
  return `${timeOfDay}, ${capitalized}.`;
}

export default async function DashboardPage() {
  const { session, user, organization } = await requireOrg("/dashboard");
  const token = (await getAccessToken()) ?? session.access_token;

  const { projects, recentExecutions, hasWork } = await getDashboardData(token);

  const displayName = user.user_metadata?.name || user.email;
  const greeting = getGreeting(displayName);

  return (
    <AppShell user={user} organizationName={organization.name}>
      <div className="mx-auto max-w-2xl px-6 py-14 md:py-20 animate-in fade-in duration-300">
        <div className="flex flex-col items-center text-center">
          {/* Editorial Greeting Headline */}
          <h1 className="text-display sm:text-[2.75rem] font-bold text-foreground mb-2 tracking-tight">
            {greeting}
          </h1>
          <p className="text-body-lg text-muted-foreground mb-8">
            What should Kova work on?
          </p>

          {/* Primary Command Center Input */}
          <DashboardCommandInput />

          {/* Workspace Activity or Intentional Empty State */}
          <div className="mt-14 w-full text-left">
            {hasWork ? (
              <div className="space-y-10">
                {projects.length > 0 && (
                  <section aria-labelledby="your-work-heading">
                    <div className="flex items-center justify-between px-1 mb-3">
                      <h2
                        id="your-work-heading"
                        className="text-caption font-medium uppercase tracking-wider text-muted-foreground/80"
                      >
                        Your work
                      </h2>
                      <span className="text-caption font-mono text-muted-foreground/60">
                        {projects.length} {projects.length === 1 ? "project" : "projects"}
                      </span>
                    </div>
                    <ProjectList projects={projects} showSearch={false} />
                  </section>
                )}

                {recentExecutions.length > 0 && (
                  <RecentExecutions executions={recentExecutions} />
                )}
              </div>
            ) : (
              <DashboardEmptyState />
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
