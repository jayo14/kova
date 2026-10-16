import { request } from "./client";

export interface ApiToken {
  id: string;
  name: string;
  scopes: string[];
  token?: string | null;
  created_at: string;
  last_used_at?: string | null;
}

export async function listTokens(): Promise<ApiToken[]> {
  return request<ApiToken[]>("GET", "/api/v1/auth/tokens");
}

export async function createToken(
  name: string,
  scopes: string[] = ["*"]
): Promise<ApiToken> {
  return request<ApiToken>("POST", "/api/v1/auth/tokens", {
    name,
    scopes,
  });
}

export async function deleteToken(id: string): Promise<void> {
  return request<void>("DELETE", `/api/v1/auth/tokens/${encodeURIComponent(id)}`);
}
