import { createServerClient as createCustomServerClient } from "./lib/auth/custom-server";
import { NextResponse, type NextRequest } from "next/server";

export async function middleware(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request });

  const supabase = createCustomServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet: any[]) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          );
          supabaseResponse = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const pathname = request.nextUrl.pathname;

  const isAuthRoute = pathname.startsWith("/auth");
  const isProtectedRoute =
    pathname.startsWith("/dashboard") ||
    pathname.startsWith("/explore") ||
    pathname.startsWith("/projects") ||
    pathname.startsWith("/flows") ||
    pathname.startsWith("/executions") ||
    pathname.startsWith("/credentials") ||
    pathname.startsWith("/organization") ||
    pathname.startsWith("/settings");

  if (isAuthRoute && user) {
    const nextPath = request.nextUrl.searchParams.get("redirect") || "/dashboard";
    const url = request.nextUrl.clone();
    url.pathname = nextPath.startsWith("/") ? nextPath : "/dashboard";
    url.search = "";
    return NextResponse.redirect(url);
  }

  if (isProtectedRoute && !user) {
    const url = request.nextUrl.clone();
    url.pathname = "/auth/login";

    if (pathname !== "/dashboard") {
      url.searchParams.set("redirect", pathname);
    }

    return NextResponse.redirect(url);
  }

  return supabaseResponse;
}

export const config = {
  matcher: [
    "/auth/:path*",
    "/dashboard/:path*",
    "/explore/:path*",
    "/explore",
    "/projects/:path*",
    "/flows/:path*",
    "/executions/:path*",
    "/credentials/:path*",
    "/organization/:path*",
    "/settings/:path*",
  ],
};
