import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  ApiError,
  isApiError,
  formatFastApiDetail,
  getErrorMessage,
} from "../errors";

import {
  normalizeExecutionStatus,
  isTerminalStatus,
  isActiveStatus,
  getExecutionStatusLabel,
  getExecutionStatusShortLabel,
} from "../../executions/status";

import {
  mapKeysToSnake,
  mapKeysToCamel,
  stripNulls,
} from "../mappers";

describe("ApiError and error normalization", () => {
  it("creates an ApiError with status, message, and details", () => {
    const err = new ApiError({
      status: 404,
      message: "Resource not found",
      details: { item: "project-123" },
    });

    assert.equal(err.status, 404);
    assert.equal(err.message, "Resource not found");
    assert.deepEqual(err.details, { item: "project-123" });
    assert.equal(isApiError(err), true);
  });

  it("identifies non-ApiError objects correctly", () => {
    assert.equal(isApiError(new Error("Generic")), false);
    assert.equal(isApiError(null), false);
    assert.equal(isApiError({ status: 500 }), false);
  });

  it("formats FastAPI validation detail arrays", () => {
    const detail = [
      { loc: ["body", "base_url"], msg: "field required" },
      { loc: ["body", "name"], msg: "ensure this value has at least 1 characters" },
    ];
    const formatted = formatFastApiDetail(detail);
    assert.equal(
      formatted,
      "base_url: field required; name: ensure this value has at least 1 characters"
    );
  });

  it("returns human-safe messages for common HTTP statuses", () => {
    assert.equal(
      getErrorMessage(new ApiError({ status: 0, message: "" })),
      "Unable to connect to Kova. Please check your connection."
    );
    assert.equal(
      getErrorMessage(new ApiError({ status: 401, message: "Unauthorized" })),
      "Session expired. Please sign in again."
    );
    assert.equal(
      getErrorMessage(new ApiError({ status: 403, message: "Forbidden" })),
      "You do not have permission to perform this action."
    );
    assert.equal(
      getErrorMessage(new ApiError({ status: 500, message: "Internal error" })),
      "A server error occurred. Please try again later."
    );
  });
});

describe("Execution status normalization and predicates", () => {
  it("normalizes uppercase backend statuses to frontend format", () => {
    assert.equal(normalizeExecutionStatus("RUNNING"), "running");
    assert.equal(normalizeExecutionStatus("BROWSER_READY"), "browser_ready");
    assert.equal(normalizeExecutionStatus("COMPLETED"), "completed");
    assert.equal(normalizeExecutionStatus("FAILED"), "failed");
    assert.equal(normalizeExecutionStatus("CANCELLED"), "cancelled");
    assert.equal(normalizeExecutionStatus("TIMEOUT"), "timeout");
  });

  it("handles empty or unknown statuses gracefully", () => {
    assert.equal(normalizeExecutionStatus(null), "created");
    assert.equal(normalizeExecutionStatus(undefined), "created");
    assert.equal(normalizeExecutionStatus("unknown_status"), "created");
  });

  it("identifies terminal and active statuses correctly", () => {
    assert.equal(isTerminalStatus("completed"), true);
    assert.equal(isTerminalStatus("failed"), true);
    assert.equal(isTerminalStatus("cancelled"), true);
    assert.equal(isTerminalStatus("timeout"), true);
    assert.equal(isTerminalStatus("running"), false);

    assert.equal(isActiveStatus("running"), true);
    assert.equal(isActiveStatus("queued"), true);
    assert.equal(isActiveStatus("completed"), false);
  });

  it("provides editorial labels for status displays", () => {
    assert.equal(getExecutionStatusLabel("running"), "Kova is working");
    assert.equal(getExecutionStatusLabel("completed"), "Completed");
    assert.equal(getExecutionStatusShortLabel("running"), "Working");
  });
});

describe("API Mappers", () => {
  it("maps camelCase keys to snake_case", () => {
    const input = {
      projectId: "p1",
      baseUrl: "https://kova.app",
      nestedData: { userRole: "admin" },
    };
    const mapped = mapKeysToSnake(input) as Record<string, unknown>;
    assert.equal(mapped.project_id, "p1");
    assert.equal(mapped.base_url, "https://kova.app");
    assert.deepEqual(mapped.nested_data, { user_role: "admin" });
  });

  it("maps snake_case keys to camelCase", () => {
    const input = {
      flow_id: "f1",
      created_at: "2026-09-16",
    };
    const mapped = mapKeysToCamel(input) as Record<string, unknown>;
    assert.equal(mapped.flowId, "f1");
    assert.equal(mapped.createdAt, "2026-09-16");
  });

  it("strips undefined values cleanly", () => {
    const input = { name: "test", desc: undefined };
    const cleaned = stripNulls(input);
    assert.equal("desc" in cleaned, false);
    assert.equal(cleaned.name, "test");
  });
});
