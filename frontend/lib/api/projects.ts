import type { Project, EnvironmentConfig, ExecutionLimits, SafetyRestrictions, BrowserSettings } from "@/lib/types";
import { api } from "./client";
import { mapKeysToCamel, mapKeysToSnake, stripNulls } from "./mappers";

export interface BackendProject {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  base_url: string;
  created_at: string;
  updated_at: string;
  product_goal?: string | null;
  env_config?: Record<string, unknown>;
  execution_limits?: Record<string, unknown>;
  safety_restrictions?: Record<string, unknown>;
  browser_settings?: Record<string, unknown>;
  test_credentials_ref?: string | null;
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
    productGoal: raw.product_goal ?? null,
    envConfig: raw.env_config ? (mapKeysToCamel(raw.env_config) as unknown as EnvironmentConfig) : undefined,
    executionLimits: raw.execution_limits ? (mapKeysToCamel(raw.execution_limits) as unknown as ExecutionLimits) : undefined,
    safetyRestrictions: raw.safety_restrictions ? (mapKeysToCamel(raw.safety_restrictions) as unknown as SafetyRestrictions) : undefined,
    browserSettings: raw.browser_settings ? (mapKeysToCamel(raw.browser_settings) as unknown as BrowserSettings) : undefined,
    testCredentialsRef: raw.test_credentials_ref ?? null,
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
  input: {
    name: string;
    description?: string | null;
    baseUrl: string;
    productGoal?: string | null;
    envConfig?: Partial<EnvironmentConfig>;
    executionLimits?: Partial<ExecutionLimits>;
    safetyRestrictions?: Partial<SafetyRestrictions>;
    browserSettings?: Partial<BrowserSettings>;
    testCredentialsRef?: string | null;
  },
  token?: string
): Promise<Project> {
  const cleanName = input.name.trim();
  const cleanBaseUrl = normalizeUrl(input.baseUrl);
  const cleanDescription = input.description?.trim() || null;

  const payload: Record<string, unknown> = {
    name: cleanName,
    description: cleanDescription,
    baseUrl: cleanBaseUrl,
  };
  if (input.productGoal !== undefined) payload.productGoal = input.productGoal;
  if (input.envConfig !== undefined) payload.envConfig = input.envConfig;
  if (input.executionLimits !== undefined) payload.executionLimits = input.executionLimits;
  if (input.safetyRestrictions !== undefined) payload.safetyRestrictions = input.safetyRestrictions;
  if (input.browserSettings !== undefined) payload.browserSettings = input.browserSettings;
  if (input.testCredentialsRef !== undefined) payload.testCredentialsRef = input.testCredentialsRef;

  const body = mapKeysToSnake(payload);
  const raw = await api.post<BackendProject>("/api/v1/projects/", body, token);
  return toFrontendProject(raw);
}

export async function updateProject(
  id: string,
  input: {
    name?: string;
    description?: string | null;
    baseUrl?: string;
    productGoal?: string | null;
    envConfig?: Partial<EnvironmentConfig>;
    executionLimits?: Partial<ExecutionLimits>;
    safetyRestrictions?: Partial<SafetyRestrictions>;
    browserSettings?: Partial<BrowserSettings>;
    testCredentialsRef?: string | null;
  },
  token?: string
): Promise<Project | null> {
  if (!id) return null;

  const payload: Record<string, unknown> = {};
  if (input.name !== undefined) payload.name = input.name.trim();
  if (input.description !== undefined) {
    payload.description = input.description ? input.description.trim() : null;
  }
  if (input.baseUrl !== undefined) payload.baseUrl = normalizeUrl(input.baseUrl);
  if (input.productGoal !== undefined) payload.productGoal = input.productGoal;
  if (input.envConfig !== undefined) payload.envConfig = input.envConfig;
  if (input.executionLimits !== undefined) payload.executionLimits = input.executionLimits;
  if (input.safetyRestrictions !== undefined) payload.safetyRestrictions = input.safetyRestrictions;
  if (input.browserSettings !== undefined) payload.browserSettings = input.browserSettings;
  if (input.testCredentialsRef !== undefined) payload.testCredentialsRef = input.testCredentialsRef;

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

import type { ProductModel, ValidationRun } from "@/lib/types";

export async function getProjectKnowledge(id: string, token?: string): Promise<ProductModel | null> {
  if (!id) return null;
  try {
    const raw = await api.get<Record<string, unknown>>(`/api/v1/projects/${encodeURIComponent(id)}/knowledge`, token);
    return mapKeysToCamel(raw) as unknown as ProductModel;
  } catch {
    return null;
  }
}

export async function getProjectValidations(id: string, token?: string): Promise<ValidationRun[]> {
  if (!id) return [];
  try {
    const raw = await api.get<Array<Record<string, unknown>>>(`/api/v1/projects/${encodeURIComponent(id)}/validations`, token);
    return raw.map((item) => mapKeysToCamel(item) as unknown as ValidationRun);
  } catch {
    return [];
  }
}
