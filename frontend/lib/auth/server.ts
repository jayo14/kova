import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
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
 * Read the Supabase access token directly from request cookies.
 * Falls back to getSession() if direct cookie reading fails.
 */
export async function getAccessToken(): Promise<string | null> {
  try {
    const supabase = await createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (session?.access_token) return session.access_token;
  } catch {
    // getSession failed, fall back to direct cookie reading
  }

  try {
    const cookieStore = await cookies();
    const all = cookieStore.getAll();

    // Supabase SSR stores the session in sb-{ref}-auth-token cookie(s).
    // It may be a single JSON cookie, base64-encoded, or split across chunks.
    const authCookies = all.filter(
      (c) => c.name.includes("auth-token") && !c.name.includes("refresh")
    );

    for (const c of authCookies) {
      try {
        let val = c.value;
        if (val.startsWith("base64-")) {
          val = Buffer.from(val.slice(7), "base64").toString("utf-8");
        }
        const parsed = JSON.parse(val);
        if (parsed.access_token) return parsed.access_token;
      } catch {
        // Not JSON — might be a chunk, skip
      }
    }
  } catch {
    // Cookie store read failed
  }

  return null;
}
