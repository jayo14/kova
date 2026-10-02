import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { subscribeToExecution } from "../executions";

describe("Realtime Execution Subscription", () => {
  it("initializes in connecting or unavailable state and provides unsubscribe", () => {
    const sub = subscribeToExecution("exec-mock-1", {});
    assert.ok(sub);
    assert.equal(sub.executionId, "exec-mock-1");
    assert.ok(typeof sub.unsubscribe === "function");
    assert.ok(typeof sub.getStatus === "function");

    // Clean up
    sub.unsubscribe();
    assert.equal(sub.getStatus(), "closed");
  });

  it("handles handler callbacks correctly on unsubscribe", () => {
    let closed = false;
    const sub = subscribeToExecution("exec-mock-2", {
      onClose: () => {
        closed = true;
      },
    });

    sub.unsubscribe();
    assert.equal(closed, true);
  });
});
