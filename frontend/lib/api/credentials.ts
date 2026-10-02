import type {
  Credential,
  CreateCredentialInput,
  UpdateCredentialInput,
} from "@/lib/types";
import { api } from "./client";
import { mapKeysToCamel } from "./mappers";
import { getProjects } from "./projects";
import { isApiError, getErrorMessage } from "./errors";

// ── Backend response shape ────────────────────────────────

export interface BackendCredential {
  id: string;
  project_id: string;
  name: string;
  email: string;
  created_at: string;
  updated_at: string;
}

// ── Mapping ───────────────────────────────────────────────

export function backendToCredential(
  raw: BackendCredential,
  projectName?: string
): Credential {
  const mapped = mapKeysToCamel(raw as unknown as Record<string, unknown>) as Record<string, unknown>;
  return {
    id: mapped.id as string,
    organizationId: "current",
    projectId: mapped.projectId as string,
    projectName: projectName ?? null,
    name: mapped.name as string,
    email: mapped.email as string,
    role: null,
    createdAt: mapped.createdAt as string,
    updatedAt: mapped.updatedAt as string,
    lastUsedAt: null,
  };
}

// ── Error Mapping ─────────────────────────────────────────

export function mapCredentialError(err: unknown, fallback: string): string {
  if (isApiError(err)) {
    if (err.status === 401) return "Session expired. Please sign in again.";
    if (err.status === 403) return "You do not have permission to manage credentials.";
    if (err.status === 404) return "The requested product or credential was not found.";
    if (err.status === 409) return "An account with this email already exists in this product.";
    if (err.status === 422) return "Invalid credential format. Please check the email and password.";
    if (err.status >= 500) return "Server error while processing test accounts. Please try again.";
    return err.message || fallback;
  }
  return getErrorMessage(err, fallback);
}

// ── Helpers ───────────────────────────────────────────────

async function resolveProjectId(
  projectId?: string,
  token?: string
): Promise<string | null> {
  if (projectId) return projectId;
  const projects = await getProjects(token);
  return projects.length > 0 ? projects[0].id : null;
}

async function getProjectName(
  projectId: string,
  token?: string
): Promise<string | undefined> {
  const projects = await getProjects(token);
  return projects.find((p) => p.id === projectId)?.name;
}

// ── Public API ────────────────────────────────────────────

export async function getCredentials(
  projectId?: string,
  token?: string
): Promise<Credential[]> {
  try {
    if (projectId) {
      const raw = await api.get<BackendCredential[]>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/credentials`,
        token
      );
      const name = await getProjectName(projectId, token);
      return raw.map((c) => backendToCredential(c, name));
    }

    const projects = await getProjects(token);
    const results = await Promise.all(
      projects.map(async (p) => {
        try {
          const raw = await api.get<BackendCredential[]>(
            `/api/v1/projects/${encodeURIComponent(p.id)}/credentials`,
            token
          );
          return raw.map((c) => backendToCredential(c, p.name));
        } catch {
          return [];
        }
      })
    );
    return results
      .flat()
      .sort(
        (a, b) =>
          new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
      );
  } catch (err) {
    throw new Error(mapCredentialError(err, "Failed to load test accounts."));
  }
}

export async function getCredential(
  id: string,
  token?: string
): Promise<Credential | null> {
  if (!id) return null;
  const projects = await getProjects(token);
  for (const p of projects) {
    try {
      const raw = await api.get<BackendCredential>(
        `/api/v1/projects/${encodeURIComponent(p.id)}/credentials/${encodeURIComponent(id)}`,
        token
      );
      return backendToCredential(raw, p.name);
    } catch {
      // Not in this project, try next
    }
  }
  return null;
}

export async function createCredential(
  input: CreateCredentialInput,
  token?: string
): Promise<Credential> {
  try {
    const pid = await resolveProjectId(input.projectId, token);
    if (!pid) throw new Error("No product available. Create a product first.");

    const body = {
      name: input.name.trim(),
      email: input.email.trim().toLowerCase(),
      password: input.password,
    };

    const raw = await api.post<BackendCredential>(
      `/api/v1/projects/${encodeURIComponent(pid)}/credentials`,
      body,
      token
    );
    const name = await getProjectName(pid, token);
    return backendToCredential(raw, name);
  } catch (err) {
    throw new Error(mapCredentialError(err, "Failed to save test account."));
  }
}

export async function updateCredential(
  id: string,
  input: UpdateCredentialInput,
  token?: string
): Promise<Credential | null> {
  if (!id) return null;
  try {
    const existing = await getCredential(id, token);
    if (!existing) return null;

    // Passwords are write-only on the backend.
    // If password changed, replace the credential securely.
    if (input.password && input.password.trim()) {
      const targetProjectId = input.projectId || existing.projectId || undefined;
      await deleteCredential(id, token, existing.projectId || undefined);
      return createCredential(
        {
          name: input.name ?? existing.name,
          email: input.email ?? existing.email,
          password: input.password,
          role: input.role || existing.role || undefined,
          projectId: targetProjectId,
        },
        token
      );
    }

    return {
      ...existing,
      ...(input.name !== undefined && { name: input.name.trim() }),
      ...(input.email !== undefined && { email: input.email.trim().toLowerCase() }),
      ...(input.role !== undefined && { role: input.role }),
      ...(input.projectId !== undefined && { projectId: input.projectId }),
      updatedAt: new Date().toISOString(),
    };
  } catch (err) {
    throw new Error(mapCredentialError(err, "Failed to update test account."));
  }
}

export async function deleteCredential(
  id: string,
  token?: string,
  projectId?: string | null
): Promise<boolean> {
  if (!id) return false;
  try {
    if (projectId) {
      await api.delete(
        `/api/v1/projects/${encodeURIComponent(projectId)}/credentials/${encodeURIComponent(id)}`,
        token
      );
      return true;
    }

    const projects = await getProjects(token);
    for (const p of projects) {
      try {
        await api.delete(
          `/api/v1/projects/${encodeURIComponent(p.id)}/credentials/${encodeURIComponent(id)}`,
          token
        );
        return true;
      } catch {
        // Not in this project, try next
      }
    }
    return false;
  } catch (err) {
    throw new Error(mapCredentialError(err, "Failed to delete test account."));
  }
}
