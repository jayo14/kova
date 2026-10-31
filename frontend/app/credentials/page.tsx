import type { Metadata } from "next";
import { requireOrg } from "@/lib/auth/guards";
import { getAccessToken } from "@/lib/auth/server";
import { AppShell } from "@/components/shell/app-shell";
import { CredentialsContent } from "@/components/credentials/credentials-content";
import { getCredentials } from "@/lib/api/credentials";
import { getProjects } from "@/lib/api/projects";

export const metadata: Metadata = {
  title: "Credentials — Kova",
  description: "Test accounts Kova can use when accessing your applications.",
};

type CredentialsSearchParams = { projectId?: string; project?: string };

export default async function CredentialsPage({
  searchParams,
}: {
  params?: Promise<unknown>;
  searchParams?: Promise<CredentialsSearchParams>;
}) {
  const { session, user, organization } = await requireOrg("/credentials");
  const token = (await getAccessToken()) ?? session.access_token;

  const resolvedParams = (await searchParams) ?? {};
  const rawProjectId = resolvedParams.projectId ?? resolvedParams.project;
  const initialProjectId = Array.isArray(rawProjectId) ? rawProjectId[0] : rawProjectId;

  const [credentials, projects] = await Promise.all([
    getCredentials(initialProjectId, token).catch(() => []),
    getProjects(token).catch(() => []),
  ]);

  return (
    <AppShell user={user} organizationName={organization.name}>
      <CredentialsContent
        initialCredentials={credentials}
        projects={projects.map((p) => ({ id: p.id, name: p.name }))}
        initialProjectId={initialProjectId}
      />
    </AppShell>
  );
}
