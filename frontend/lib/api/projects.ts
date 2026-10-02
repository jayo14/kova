import type { Project } from "@/lib/types";
import { api } from "./client";
import { mapKeysToSnake, stripNulls } from "./mappers";

export interface BackendProject {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  base_url: string;
  created_at: string;
  updated_at: string;
}

export function toFrontendProject(raw: BackendProject): Project {
  return {
    id: raw.id,
    userId: raw.user_id,
    name: raw.name,
    description: raw.description ?? null,
    baseUrl: raw.base_url,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
}

function normalizeUrl(url: string): string {
  const trimmed = url.trim();
  if (!/^https?:\/\//i.test(trimmed)) {
    return `https://${trimmed}`;
  }
  return trimmed;
}

export async function getProjects(token?: string): Promise<Project[]> {
  const raw = await api.get<BackendProject[]>("/api/v1/projects/", token);
  return raw.map(toFrontendProject);
}

export async function getProject(id: string, token?: string): Promise<Project | null> {
  if (!id) return null;
  try {
    const raw = await api.get<BackendProject>(`/api/v1/projects/${encodeURIComponent(id)}`, token);
    return toFrontendProject(raw);
  } catch {
    return null;
  }
}

export async function createProject(
  input: { name: string; description?: string | null; baseUrl: string },
  token?: string
): Promise<Project> {
  const cleanName = input.name.trim();
  const cleanBaseUrl = normalizeUrl(input.baseUrl);
  const cleanDescription = input.description?.trim() || null;

  const body = mapKeysToSnake({
    name: cleanName,
    description: cleanDescription,
    baseUrl: cleanBaseUrl,
  });

  const raw = await api.post<BackendProject>("/api/v1/projects/", body, token);
  return toFrontendProject(raw);
}

export async function updateProject(
  id: string,
  input: { name?: string; description?: string | null; baseUrl?: string },
  token?: string
): Promise<Project | null> {
  if (!id) return null;

  const payload: Record<string, unknown> = {};
  if (input.name !== undefined) payload.name = input.name.trim();
  if (input.description !== undefined) {
    payload.description = input.description ? input.description.trim() : null;
  }
  if (input.baseUrl !== undefined) payload.baseUrl = normalizeUrl(input.baseUrl);

  const body = stripNulls(mapKeysToSnake(payload));
  try {
    const raw = await api.put<BackendProject>(
      `/api/v1/projects/${encodeURIComponent(id)}`,
      body,
      token
    );
    return toFrontendProject(raw);
  } catch {
    return null;
  }
}

export async function deleteProject(id: string, token?: string): Promise<boolean> {
  if (!id) return false;
  try {
    await api.delete(`/api/v1/projects/${encodeURIComponent(id)}`, token);
    return true;
  } catch {
    return false;
  }
}
