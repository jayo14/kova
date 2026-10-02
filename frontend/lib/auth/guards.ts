import { redirect } from "next/navigation";
import { getSession, getUser } from "./session";
import { resolveUserOrganization, getActiveOrganization } from "./organization";
import type { Session, User } from "@supabase/supabase-js";
import type { Organization } from "@/lib/types";

export interface AuthenticatedContext {
  session: Session;
  user: User;
  organization: Organization;
}

/**
 * Server guard requiring an active Supabase session.
 * Redirects unauthenticated requests to login page with preserved redirect path.
 */
export async function requireAuth(returnPath?: string): Promise<Session> {
  const session = await getSession();
  if (!session) {
    const destination = returnPath
      ? `/auth/login?redirect=${encodeURIComponent(returnPath)}`
      : "/auth/login";
    redirect(destination);
  }
  return session;
}

/**
 * Server guard preventing authenticated users from viewing auth routes (login/signup).
 */
export async function requireNoAuth(destination: string = "/dashboard"): Promise<void> {
  const session = await getSession();
  if (session) {
    redirect(destination);
  }
}

/**
 * Server guard requiring authenticated user and resolved organization context.
 */
export async function requireOrg(returnPath?: string): Promise<AuthenticatedContext> {
  const session = await requireAuth(returnPath);
  const user = (await getUser()) || session.user;

  const organization = user
    ? resolveUserOrganization(user)
    : getActiveOrganization();

  return {
    session,
    user,
    organization,
  };
}
