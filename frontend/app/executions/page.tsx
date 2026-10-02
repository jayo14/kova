import type { Metadata } from "next";
import { requireOrg } from "@/lib/auth/guards";
import { getAccessToken } from "@/lib/auth/server";
import { AppShell } from "@/components/shell/app-shell";
import { getExecutions } from "@/lib/api/executions";
import { ExecutionList } from "@/components/executions";

export const metadata: Metadata = {
  title: "Executions — Kova",
  description: "Runs Kova has performed across your products.",
};

export default async function ExecutionsPage() {
  const { session, user, organization } = await requireOrg("/executions");
  const token = (await getAccessToken()) ?? session.access_token;

  const executions = await getExecutions(undefined, token).catch(() => []);

  return (
    <AppShell user={user} organizationName={organization.name}>
      <div className="w-full max-w-5xl mx-auto px-6 py-10 md:py-14 animate-in fade-in duration-300">
        <div className="mb-8">
          <h1 className="text-display sm:text-[2.25rem] font-bold text-foreground mb-1.5 tracking-tight">
            Executions
          </h1>
          <p className="text-body-sm text-muted-foreground leading-relaxed">
            Runs Kova has performed.
          </p>
        </div>

        <ExecutionList executions={executions} />
      </div>
    </AppShell>
  );
}
