import { createServerClient as createCustomServerClient } from "./custom-server";
import { cookies } from "next/headers";

export async function createClient() {
  const cookieStore = await cookies();

  return createCustomServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet: any[]) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          } catch {
            // Server component — ignore
          }
        },
      },
    }
  );
}

/**
 * Read the access token directly from request cookies.
 */
export async function getAccessToken(): Promise<string | null> {
  try {
    const cookieStore = await cookies();
    const token = cookieStore.get("access_token");
    if (token?.value) return token.value;
  } catch {
    // Cookie store read failed
  }
  return null;
}
