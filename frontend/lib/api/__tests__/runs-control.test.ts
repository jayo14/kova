import test, { describe } from "node:test";
import assert from "node:assert/strict";
import { pauseRun, resumeRun, getRunControl } from "../runs";
import {
  getExecutionControl,
  pauseExecution,
  resumeExecution,
  takeoverExecution,
  releaseExecutionControl,
} from "../executions";

describe("Run & Execution Control API Client", () => {
  test("pauseRun sends POST request with reason", async () => {
    const originalFetch = globalThis.fetch;
    let calledUrl = "";
    let calledMethod = "";
    let calledBody: any = null;

    globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
      calledUrl = String(url);
      calledMethod = init?.method || "GET";
      calledBody = init?.body ? JSON.parse(String(init.body)) : null;

      return {
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          run_id: "run-999",
          status: "PAUSED",
          active_executions: 1,
          paused_executions: 1,
        }),
      } as unknown as Response;
    }) as typeof fetch;

    try {
      const res = await pauseRun("run-999", "Testing pause");
      assert.match(calledUrl, /\/api\/v1\/runs\/run-999\/pause$/);
      assert.equal(calledMethod, "POST");
      assert.equal(calledBody.reason, "Testing pause");
      assert.equal(res.status, "PAUSED");
      assert.equal(res.paused_executions, 1);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test("resumeRun sends POST request without body", async () => {
    const originalFetch = globalThis.fetch;
    let calledUrl = "";
    let calledMethod = "";

    globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
      calledUrl = String(url);
      calledMethod = init?.method || "GET";

      return {
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          run_id: "run-999",
          status: "RUNNING",
          active_executions: 1,
          resumed_executions: 1,
        }),
      } as unknown as Response;
    }) as typeof fetch;

    try {
      const res = await resumeRun("run-999");
      assert.match(calledUrl, /\/api\/v1\/runs\/run-999\/resume$/);
      assert.equal(calledMethod, "POST");
      assert.equal(res.status, "RUNNING");
      assert.equal(res.resumed_executions, 1);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test("getRunControl maps run status correctly", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = (async (url: string | URL | Request) => {
      assert.match(String(url), /\/api\/v1\/runs\/run-999\/control$/);
      return {
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          run_id: "run-999",
          status: "PAUSED",
          state: "paused",
          active_executions: 1,
          paused_executions: 1,
          executions: [],
        }),
      } as unknown as Response;
    }) as typeof fetch;

    try {
      const res = await getRunControl("run-999");
      assert.equal(res.run_id, "run-999");
      assert.equal(res.state, "paused");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test("execution control methods invoke respective endpoints", async () => {
    const originalFetch = globalThis.fetch;
    const calls: { url: string; method: string; body: any }[] = [];

    globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({
        url: String(url),
        method: init?.method || "GET",
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });

      return {
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          execution_id: "ex-123",
          state: "paused",
          generation: 2,
        }),
      } as unknown as Response;
    }) as typeof fetch;

    try {
      await getExecutionControl("ex-123");
      await pauseExecution("ex-123", "inspect dom");
      await takeoverExecution("ex-123", { client_id: "client-a" });
      await releaseExecutionControl("ex-123", { client_id: "client-a", lease_id: "lease-1" });
      await resumeExecution("ex-123");

      assert.equal(calls.length, 5);
      assert.match(calls[0].url, /\/api\/v1\/executions\/ex-123\/control$/);
      assert.equal(calls[0].method, "GET");

      assert.match(calls[1].url, /\/api\/v1\/executions\/ex-123\/pause$/);
      assert.equal(calls[1].method, "POST");
      assert.equal(calls[1].body.reason, "inspect dom");

      assert.match(calls[2].url, /\/api\/v1\/executions\/ex-123\/takeover$/);
      assert.equal(calls[2].method, "POST");
      assert.equal(calls[2].body.client_id, "client-a");

      assert.match(calls[3].url, /\/api\/v1\/executions\/ex-123\/release$/);
      assert.equal(calls[3].method, "POST");
      assert.equal(calls[3].body.lease_id, "lease-1");

      assert.match(calls[4].url, /\/api\/v1\/executions\/ex-123\/resume$/);
      assert.equal(calls[4].method, "POST");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
