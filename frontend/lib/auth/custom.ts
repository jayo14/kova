import Cookies from "js-cookie";

export type User = { id: string; email: string; name?: string; user_metadata?: any };
export type Session = { access_token: string; user: User };

let _cachedUser: User | null = null;
let _cachedToken: string | null = null;
let _cachedUserExpiresAt = 0;
let _lastRateLimitedAt = 0;
let _inFlightUserPromise: Promise<{ data: { user: User | null }; error: any }> | null = null;
const USER_CACHE_TTL_MS = 60_000;
const RATE_LIMIT_BACKOFF_MS = 30_000;

function parseJwtPayload(token: string): any | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const base64Url = parts[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(jsonPayload);
  } catch {
    return null;
  }
}

export class CustomAuthClient {
  private listeners: any[] = [];
  
  public auth = {
    getUser: async () => {
      let token;
      if (typeof window !== "undefined") {
        token = Cookies.get("access_token");
      }
      
      if (!token) {
        _cachedUser = null;
        _cachedToken = null;
        return { data: { user: null }, error: null };
      }

      // 1. Fast in-memory cache hit
      if (_cachedUser && _cachedToken === token && Date.now() < _cachedUserExpiresAt) {
        return { data: { user: _cachedUser }, error: null };
      }

      // 2. If recently rate-limited (HTTP 429), avoid spamming backend and decode locally
      if (Date.now() - _lastRateLimitedAt < RATE_LIMIT_BACKOFF_MS) {
        if (_cachedUser && _cachedToken === token) {
          return { data: { user: _cachedUser }, error: null };
        }
        const payload = parseJwtPayload(token);
        if (payload && (payload.sub || payload.id)) {
          const fallbackUser: User = {
            id: payload.sub || payload.id,
            email: payload.email || "",
            name: payload.user_metadata?.name || payload.name || undefined,
          };
          _cachedUser = fallbackUser;
          _cachedToken = token;
          _cachedUserExpiresAt = Date.now() + USER_CACHE_TTL_MS;
          return { data: { user: fallbackUser }, error: null };
        }
      }

      // 3. Deduplicate concurrent in-flight requests
      if (_inFlightUserPromise) {
        return _inFlightUserPromise;
      }

      _inFlightUserPromise = (async () => {
        try {
          const res = await fetch("/api/v1/auth/me", {
            headers: { Authorization: `Bearer ${token}` }
          });
          if (!res.ok) {
            if (res.status === 429) {
              _lastRateLimitedAt = Date.now();
            }
            // If rate-limited or transient network error, fall back to cached user or decoded JWT payload
            if (_cachedUser && _cachedToken === token) {
              return { data: { user: _cachedUser }, error: null };
            }
            const payload = parseJwtPayload(token);
            if (payload && (payload.sub || payload.id)) {
              const fallbackUser: User = {
                id: payload.sub || payload.id,
                email: payload.email || "",
                name: payload.user_metadata?.name || payload.name || undefined,
              };
              _cachedUser = fallbackUser;
              _cachedToken = token;
              _cachedUserExpiresAt = Date.now() + USER_CACHE_TTL_MS;
              return { data: { user: fallbackUser }, error: null };
            }
            return { data: { user: null }, error: new Error("Not logged in") };
          }
          const user = await res.json();
          _cachedUser = user;
          _cachedToken = token;
          _cachedUserExpiresAt = Date.now() + USER_CACHE_TTL_MS;
          return { data: { user }, error: null };
        } catch (err) {
          // Fall back to decoded JWT token if offline or transient fetch failure
          const payload = parseJwtPayload(token);
          if (payload && (payload.sub || payload.id)) {
            const fallbackUser: User = {
              id: payload.sub || payload.id,
              email: payload.email || "",
              name: payload.user_metadata?.name || payload.name || undefined,
            };
            return { data: { user: fallbackUser }, error: null };
          }
          return { data: { user: null }, error: err };
        }
      })().finally(() => {
        _inFlightUserPromise = null;
      });

      return _inFlightUserPromise;
    },
    
    getSession: async () => {
      let token;
      if (typeof window !== "undefined") {
        token = Cookies.get("access_token");
      }
      if (!token) return { data: { session: null }, error: null };
      
      try {
        // Fast path: if token matches cached user, return immediately without network
        if (_cachedUser && _cachedToken === token && Date.now() < _cachedUserExpiresAt) {
          return { data: { session: { access_token: token, user: _cachedUser } }, error: null };
        }
        const { data: { user } } = await this.auth.getUser();
        if (!user) {
          // If token exists, don't drop session on transient user fetch error
          const payload = parseJwtPayload(token);
          if (payload && (payload.sub || payload.id)) {
            const fallbackUser: User = {
              id: payload.sub || payload.id,
              email: payload.email || "",
              name: payload.name || undefined,
            };
            return { data: { session: { access_token: token, user: fallbackUser } }, error: null };
          }
          return { data: { session: null }, error: null };
        }
        return { data: { session: { access_token: token, user } }, error: null };
      } catch (err) {
        return { data: { session: null }, error: err };
      }
    },
    
    signInWithPassword: async ({ email, password }: any) => {
      try {
        const res = await fetch("/api/v1/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password })
        });
        const data = await res.json();
        if (!res.ok) return { data: { user: null }, error: new Error(data.detail || "Login failed") };
        
        Cookies.set("access_token", data.access_token, { expires: 7, path: '/' });
        this.notify(data.session);
        return { data: { user: data.user, session: { access_token: data.access_token, user: data.user } }, error: null };
      } catch (err) {
        return { data: { user: null }, error: err };
      }
    },
    
    signUp: async ({ email, password, options }: any) => {
      try {
        const res = await fetch("/api/v1/auth/register", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password, name: options?.data?.name })
        });
        const data = await res.json();
        if (!res.ok) return { data: { user: null }, error: new Error(data.detail || "Registration failed") };
        
        Cookies.set("access_token", data.access_token, { expires: 7, path: '/' });
        this.notify(data.session);
        return { data: { user: data.user, session: { access_token: data.access_token, user: data.user } }, error: null };
      } catch (err) {
        return { data: { user: null }, error: err };
      }
    },
    
    signOut: async () => {
      _cachedUser = null;
      _cachedToken = null;
      _cachedUserExpiresAt = 0;
      Cookies.remove("access_token", { path: '/' });
      this.notify(null);
      return { error: null };
    },
    
    onAuthStateChange: (callback: any) => {
      this.listeners.push(callback);
      return {
        data: {
          subscription: { unsubscribe: () => {
            this.listeners = this.listeners.filter(cb => cb !== callback);
          }}
        }
      };
    },

    resetPasswordForEmail: async (email: string, options?: any) => {
      try {
        const res = await fetch("/api/v1/auth/reset-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email })
        });
        if (!res.ok) return { data: { user: null }, error: new Error("Failed to send reset email") };
        return { data: { user: null }, error: null };
      } catch (err) {
        return { data: { user: null }, error: err };
      }
    },
    
    exchangeCodeForSession: async (code: string) => {
      if (code) {
        Cookies.set("access_token", code, { expires: 1, path: "/" });
        return { data: { session: { access_token: code, user: null as any } }, error: null };
      }
      return { data: { session: null }, error: new Error("Invalid code or token") };
    },
    
    updateUser: async (attrs: any) => {
      let token = "";
      if (typeof window !== "undefined") {
        token = Cookies.get("access_token") || "";
      }
      if (!token && attrs?.token) {
        token = attrs.token;
      }
      if (!token) {
        return { data: { user: null }, error: new Error("Not authenticated") };
      }

      try {
        if (attrs?.password) {
          // First attempt change-password (for authenticated session)
          const res = await fetch("/api/v1/auth/change-password", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({ new_password: attrs.password, password: attrs.password }),
          });

          if (!res.ok) {
            // If failed (e.g. 401 unauthenticated), try reset-password/confirm with the token
            const resetRes = await fetch("/api/v1/auth/reset-password/confirm", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ token, new_password: attrs.password }),
            });
            const resetData = await resetRes.json().catch(() => ({}));
            if (!resetRes.ok) {
              return { data: { user: null }, error: new Error(resetData.detail || "Failed to update password") };
            }
            return { data: { user: null }, error: null };
          }

          const { data } = await this.auth.getUser();
          return { data: { user: data.user }, error: null };
        }

        const { data } = await this.auth.getUser();
        return { data: { user: data.user }, error: null };
      } catch (err: any) {
        return { data: { user: null }, error: err };
      }
    },
    
    deleteUser: async () => {
      let token = "";
      if (typeof window !== "undefined") {
        token = Cookies.get("access_token") || "";
      }
      if (!token) return { data: { user: null }, error: new Error("Not logged in") };
      try {
        const res = await fetch("/api/v1/auth/me", {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          return { data: { user: null }, error: new Error(data.detail || "Failed to delete account") };
        }
        Cookies.remove("access_token", { path: "/" });
        this.notify(null);
        return { data: { user: null }, error: null };
      } catch (err: any) {
        return { data: { user: null }, error: err };
      }
    },

    refreshSession: async () => {
      return await this.auth.getSession();
    },
    
    admin: {
      deleteUser: async (id?: string) => {
        return await this.auth.deleteUser();
      }
    }
  };

  private notify(session: any) {
    this.listeners.forEach(cb => cb("SIGNED_IN", session));
  }
}

export function createClient() {
  return new CustomAuthClient();
}
