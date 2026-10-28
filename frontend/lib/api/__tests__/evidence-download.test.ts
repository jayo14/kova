import test, { describe } from "node:test";
import assert from "node:assert/strict";
import { downloadExecutionTrace } from "../evidence";

describe("Authenticated evidence downloads", () => {
  test("sends bearer auth in headers and never places it in the URL", async () => {
    const originalFetch = globalThis.fetch;
    const originalWindow = globalThis.window;
    const originalDocument = globalThis.document;
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    let requestUrl = "";
    let authorization = "";
    let downloadedAs = "";
    const fakeDocument = {
      cookie: "access_token=secret-session-token",
      createElement: () => ({
        href: "",
        download: "",
        click() { downloadedAs = this.download; },
      }),
    } as unknown as Document;

    Object.defineProperty(globalThis, "window", { configurable: true, value: {} });
    Object.defineProperty(globalThis, "document", { configurable: true, value: fakeDocument });
    URL.createObjectURL = (() => "blob:trace") as typeof URL.createObjectURL;
    URL.revokeObjectURL = (() => undefined) as typeof URL.revokeObjectURL;
    globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
      requestUrl = String(url);
      authorization = new Headers(init?.headers).get("Authorization") ?? "";
      return {
        ok: true,
        status: 200,
        blob: async () => new Blob(["trace"]),
      } as Response;
    }) as typeof fetch;

    try {
      await downloadExecutionTrace("execution-123");
      assert.equal(authorization, "Bearer secret-session-token");
      assert.equal(requestUrl.includes("secret-session-token"), false);
      assert.equal(new URL(requestUrl).search, "");
      assert.equal(downloadedAs, "trace_execution-123.zip");
    } finally {
      globalThis.fetch = originalFetch;
      Object.defineProperty(globalThis, "window", { configurable: true, value: originalWindow });
      Object.defineProperty(globalThis, "document", { configurable: true, value: originalDocument });
      URL.createObjectURL = originalCreateObjectURL;
      URL.revokeObjectURL = originalRevokeObjectURL;
    }
  });
});
