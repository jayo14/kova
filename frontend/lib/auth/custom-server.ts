export type CookieEntry = { name: string; value: string };
export type CookieToSet = { name: string; value: string; options?: unknown };

export type ServerClientOptions = {
  cookies?: {
    getAll?: () => CookieEntry[];
    setAll?: (cookies: CookieToSet[]) => void;
  };
};

function toError(err: unknown): Error {
  return err instanceof Error ? err : new Error(String(err));
}

export class CustomServerClient {
  constructor(private cookiesRef: ServerClientOptions) {}

  private readCookies(): CookieEntry[] {
    const getAll = this.cookiesRef.cookies?.getAll;
    return typeof getAll === "function" ? getAll() : [];
  }

  public auth = {
    getUser: async () => {
      // Very naive JWT decoding for middleware just to check if token exists and is valid format
      // In production, the middleware should verify the token signature
      const cookies = this.readCookies();
      const tokenObj = cookies.find((c) => c.name === "access_token");
      const token = tokenObj?.value;

      if (!token) return { data: { user: null }, error: null };

      try {
        const payloadStr = Buffer.from(token.split('.')[1], 'base64').toString();
        const payload = JSON.parse(payloadStr);
        if (payload.exp * 1000 < Date.now()) {
          return { data: { user: null }, error: new Error("Token expired") };
        }
        return { data: { user: { id: payload.sub, email: payload.email, user_metadata: payload.user_metadata } }, error: null };
      } catch (err) {
        return { data: { user: null }, error: toError(err) };
      }
    },
    getSession: async () => {
      const userRes = await this.auth.getUser();
      if (!userRes.data.user) return { data: { session: null }, error: null };

      const cookies = this.readCookies();
      const tokenObj = cookies.find((c) => c.name === "access_token");
      return { data: { session: { access_token: tokenObj?.value ?? "", user: userRes.data.user } }, error: null };
    }
  };
}

export function createServerClient(url: string, key: string, options: ServerClientOptions) {
  return new CustomServerClient(options);
}
