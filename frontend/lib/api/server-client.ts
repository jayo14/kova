import { getSession } from "@/lib/auth/session";
import { api } from "./client";

export async function getServerToken(): Promise<string | null> {
  const session = await getSession();
  return session?.access_token ?? null;
}

export async function serverApiRequest<T>(
  method: string,
  path: string,
  body?: unknown
): Promise<T> {
  const token = await getServerToken();
  switch (method) {
    case "GET":
      return api.get<T>(path, token ?? undefined);
    case "POST":
      return api.post<T>(path, body, token ?? undefined);
    case "PUT":
      return api.put<T>(path, body, token ?? undefined);
    case "PATCH":
      return api.patch<T>(path, body, token ?? undefined);
    case "DELETE":
      return api.delete<T>(path, token ?? undefined);
    default:
      throw new Error(`Unsupported method: ${method}`);
  }
}

export const serverApi = {
  get: <T>(path: string) => serverApiRequest<T>("GET", path),
  post: <T>(path: string, body?: unknown) =>
    serverApiRequest<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) =>
    serverApiRequest<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) =>
    serverApiRequest<T>("PATCH", path, body),
  delete: <T>(path: string) => serverApiRequest<T>("DELETE", path),
};
