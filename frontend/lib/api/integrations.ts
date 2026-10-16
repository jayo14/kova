import { apiClient } from "./client";

export interface Integration {
  id: string;
  projectId: string;
  provider: "github" | "gitlab";
  providerRepoId: string;
  providerInstallationId?: string | null;
  defaultBranch: string;
  kovaConfigPath: string;
  active: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface CreateIntegrationInput {
  provider: "github" | "gitlab";
  provider_repo_id: string;
  webhook_secret: string;
  access_token?: string;
  provider_installation_id?: string;
  default_branch?: string;
  kova_config_path?: string;
}

export async function getProjectIntegrations(projectId: string): Promise<Integration[]> {
  const resp = await apiClient.get<Array<Record<string, unknown>>>(
    `/api/v1/projects/${projectId}/integrations`
  );
  return (resp || []).map((item) => ({
    id: String(item.id),
    projectId: String(item.project_id || projectId),
    provider: (item.provider as "github" | "gitlab") || "github",
    providerRepoId: String(item.provider_repo_id || ""),
    providerInstallationId: item.provider_installation_id ? String(item.provider_installation_id) : null,
    defaultBranch: String(item.default_branch || "main"),
    kovaConfigPath: String(item.kova_config_path || ".kova.yml"),
    active: Boolean(item.active),
    createdAt: String(item.created_at || ""),
    updatedAt: String(item.updated_at || ""),
  }));
}

export async function createProjectIntegration(
  projectId: string,
  input: CreateIntegrationInput
): Promise<Integration> {
  const resp = await apiClient.post<Record<string, unknown>>(
    `/api/v1/projects/${projectId}/integrations`,
    {
      project_id: projectId,
      ...input,
    }
  );
  return {
    id: String(resp.id),
    projectId: String(resp.project_id || projectId),
    provider: (resp.provider as "github" | "gitlab") || "github",
    providerRepoId: String(resp.provider_repo_id || ""),
    providerInstallationId: resp.provider_installation_id ? String(resp.provider_installation_id) : null,
    defaultBranch: String(resp.default_branch || "main"),
    kovaConfigPath: String(resp.kova_config_path || ".kova.yml"),
    active: Boolean(resp.active),
    createdAt: String(resp.created_at || ""),
    updatedAt: String(resp.updated_at || ""),
  };
}

export async function deactivateProjectIntegration(
  projectId: string,
  integrationId: string
): Promise<boolean> {
  await apiClient.delete(`/api/v1/projects/${projectId}/integrations/${integrationId}`);
  return true;
}
