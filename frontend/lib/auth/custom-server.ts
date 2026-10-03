export class CustomServerClient {
  constructor(private cookiesRef: any) {}

  public auth = {
    getUser: async () => {
      // Very naive JWT decoding for middleware just to check if token exists and is valid format
      // In production, the middleware should verify the token signature
      const cookies = typeof this.cookiesRef.getAll === 'function' 
        ? this.cookiesRef.getAll() 
        : [];
      const tokenObj = cookies.find((c: any) => c.name === "access_token");
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
        return { data: { user: null }, error: err };
      }
    },
    getSession: async () => {
      const userRes = await this.auth.getUser();
      if (!userRes.data.user) return { data: { session: null }, error: null };
      
      const cookies = typeof this.cookiesRef.getAll === 'function' ? this.cookiesRef.getAll() : [];
      const tokenObj = cookies.find((c: any) => c.name === "access_token");
      return { data: { session: { access_token: tokenObj?.value, user: userRes.data.user } }, error: null };
    }
  };
}

export function createServerClient(url: string, key: string, options: any) {
  return new CustomServerClient(options.cookies);
}
