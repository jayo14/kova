import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";

import {
  getCurrentSessionId,
  setCurrentSessionId,
  getCurrentProjectId,
  setCurrentProjectId,
  normalizeExploreStatus,
  normalizeTargetUrl,
  submitCredential,
  submitExistingCredential,
  createAccount,
} from "../exploration";

describe("Exploration Session and Sandboxed Credential Management", () => {
  beforeEach(() => {
    setCurrentSessionId(null);
    setCurrentProjectId(null);
  });

  it("manages session id setter and getter", () => {
    assert.equal(getCurrentSessionId(), null);
    setCurrentSessionId("sess-12345");
    assert.equal(getCurrentSessionId(), "sess-12345");
    setCurrentSessionId(null);
    assert.equal(getCurrentSessionId(), null);
  });

  it("manages project id setter and getter", () => {
    assert.equal(getCurrentProjectId(), null);
    setCurrentProjectId("proj-67890");
    assert.equal(getCurrentProjectId(), "proj-67890");
    setCurrentProjectId(null);
    assert.equal(getCurrentProjectId(), null);
  });

  it("normalizes exploration statuses accurately", () => {
    assert.equal(normalizeExploreStatus("CREATED"), "connecting");
    assert.equal(normalizeExploreStatus("connecting"), "connecting");
    assert.equal(normalizeExploreStatus("LOADING"), "loading");
    assert.equal(normalizeExploreStatus("VALIDATING_PAGE"), "validating_page");
    assert.equal(normalizeExploreStatus("AUTH_REQUIRED"), "auth_required");
    assert.equal(normalizeExploreStatus("AUTHENTICATING"), "authenticating");
    assert.equal(normalizeExploreStatus("READY"), "ready");
    assert.equal(normalizeExploreStatus("FAILED"), "failed");
  });

  it("normalizes target URLs", () => {
    assert.equal(normalizeTargetUrl("example.com"), "https://example.com");
    assert.equal(normalizeTargetUrl("http://localhost:3000"), "http://localhost:3000");
    assert.equal(normalizeTargetUrl("https://quiza-ai.vercel.app/signin"), "https://quiza-ai.vercel.app/signin");
  });

  it("throws 'No active exploration session' only when no session id is provided or stored", async () => {
    setCurrentSessionId(null);
    const events: any[] = [];

    await assert.rejects(
      async () => {
        await submitCredential("test@example.com", "pass123", (e) => events.push(e));
      },
      {
        name: "Error",
        message: "No active exploration session",
      }
    );

    await assert.rejects(
      async () => {
        await submitExistingCredential("cred-123", (e) => events.push(e));
      },
      {
        name: "Error",
        message: "No active exploration session",
      }
    );

    await assert.rejects(
      async () => {
        await createAccount("new@example.com", "pass123", (e) => events.push(e));
      },
      {
        name: "Error",
        message: "No active exploration session",
      }
    );
  });

  it("accepts an explicit sessionId even if module state is not yet initialized", async () => {
    setCurrentSessionId(null);
    assert.equal(getCurrentSessionId(), null);

    const events: any[] = [];
    // Even if fetch fails because backend is not running, it must NOT throw "No active exploration session"
    // Instead it transitions state to authenticating, updates currentSessionId, and catches the network error.
    await submitCredential(
      "test@example.com",
      "pass123",
      (e) => events.push(e),
      undefined,
      undefined,
      "recovered-session-uuid"
    );

    // Verify targetSessionId was saved
    assert.equal(getCurrentSessionId(), "recovered-session-uuid");
    assert.ok(events.some((e) => e.type === "state_change" && e.state === "authenticating"));
  });
});
