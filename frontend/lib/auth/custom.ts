import Cookies from "js-cookie";

export type User = { id: string; email: string; name?: string; user_metadata?: any };
export type Session = { access_token: string; user: User };

export class CustomAuthClient {
  private listeners: any[] = [];
  
  public auth = {
    getUser: async () => {
      let token;
      if (typeof window !== "undefined") {
        token = Cookies.get("access_token");
      }
      
      if (!token) return { data: { user: null }, error: null };
      
      try {
        const res = await fetch("/api/v1/auth/me", {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (!res.ok) return { data: { user: null }, error: new Error("Not logged in") };
        const user = await res.json();
        return { data: { user }, error: null };
      } catch (err) {
        return { data: { user: null }, error: err };
      }
    },
    
    getSession: async () => {
      let token;
      if (typeof window !== "undefined") {
        token = Cookies.get("access_token");
      }
      if (!token) return { data: { session: null }, error: null };
      
      try {
        const { data: { user } } = await this.auth.getUser();
        if (!user) return { data: { session: null }, error: null };
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
