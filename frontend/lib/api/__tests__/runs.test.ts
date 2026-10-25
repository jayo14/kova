import test, { describe } from "node:test";
import assert from "node:assert/strict";
import { createRun, getRun, cancelRun, streamRunEvents } from "../runs";

describe("Run Orchestration API Client", () => {
  test("createRun formats payload and maps response", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
      assert.match(String(url), /\/api\/v1\/runs$/);
      assert.equal(init?.method, "POST");
      const body = JSON.parse(String(init?.body));
      assert.equal(body.project_id, "proj-123");
      assert.deepEqual(body.execution_ids, ["ex-1", "ex-2"]);
      assert.equal(body.concurrency_limit, 2);
      assert.equal(body.parallel, true);

      return {
        ok: true,
        status: 201,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          id: "run-abc",
          project_id: "proj-123",
          status: "RUNNING",
          summary: {
            total: 2,
            queued: 2,
            running: 0,
            passed: 0,
            failed: 0,
            blocked: 0,
          },
          execution_ids: ["ex-1", "ex-2"],
          created_at: "2026-10-25T15:00:00Z",
        }),
      } as unknown as Response;
    }) as typeof fetch;

    try {
      const result = await createRun({
        projectId: "proj-123",
        executionIds: ["ex-1", "ex-2"],
        concurrencyLimit: 2,
        parallel: true,
      });

      assert.equal(result.id, "run-abc");
      assert.equal(result.status, "RUNNING");
      assert.equal(result.summary.total, 2);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test("getRun maps snake_case properties to camelCase", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async (url: string | URL | Request) => {
      assert.match(String(url), /\/api\/v1\/runs\/run-abc$/);

      return {
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          id: "run-abc",
          project_id: "proj-123",
          status: "RUNNING",
          summary: {
            total: 2,
            queued: 0,
            running: 1,
            passed: 1,
            failed: 0,
            blocked: 0,
          },
          progress: 50,
          created_at: "2026-10-25T15:00:00Z",
          completed_at: null,
          executions: [
            {
              id: "ex-1",
              flow_id: "flow-1",
              mission_name: "Quiz Flow",
              status: "COMPLETED",
              duration_ms: 4500,
            },
            {
              id: "ex-2",
              flow_id: "flow-2",
              mission_name: "Study Flow",
              status: "RUNNING",
              duration_ms: null,
            },
          ],
        }),
      } as unknown as Response;
    }) as typeof fetch;

    try {
      const run = await getRun("run-abc");
      assert.equal(run.id, "run-abc");
      assert.equal(run.projectId, "proj-123");
      assert.equal(run.progress, 50);
      assert.equal(run.executions.length, 2);
      assert.equal(run.executions[0].missionName, "Quiz Flow");
      assert.equal(run.executions[0].durationMs, 4500);
      assert.equal(run.executions[1].status, "RUNNING");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test("cancelRun sends cancel request and returns updated status", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
      assert.match(String(url), /\/api\/v1\/runs\/run-abc\/cancel$/);
      assert.equal(init?.method, "POST");

      return {
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          id: "run-abc",
          project_id: "proj-123",
          status: "CANCELLED",
          summary: {
            total: 1,
            queued: 0,
            running: 0,
            passed: 0,
            failed: 0,
            blocked: 0,
          },
          progress: 0,
          executions: [],
        }),
      } as unknown as Response;
    }) as typeof fetch;

    try {
      const res = await cancelRun("run-abc");
      assert.equal(res.status, "CANCELLED");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
