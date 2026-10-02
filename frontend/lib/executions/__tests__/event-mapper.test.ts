import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  validateExecutionEvent,
  sanitizePayload,
  sanitizeText,
  mapExecutionEvent,
  mapExecutionEvents,
  deduplicateEvents,
} from "../event-mapper";
import type { ExecutionEvent } from "@/lib/types";

describe("Execution Event Validation", () => {
  it("validates and accepts valid ExecutionEvent structure", () => {
    const raw = {
      id: "ev-1",
      execution_id: "ex-100",
      event_type: "action.started",
      payload: { action: "click", target: "Submit" },
      created_at: "2026-09-16T10:00:00.000Z",
    };

    const validated = validateExecutionEvent(raw);
    assert.ok(validated);
    assert.equal(validated.id, "ev-1");
    assert.equal(validated.executionId, "ex-100");
    assert.equal(validated.eventType, "action.started");
    assert.equal(validated.payload.target, "Submit");
  });

  it("rejects malformed events missing required fields", () => {
    assert.equal(validateExecutionEvent(null), null);
    assert.equal(validateExecutionEvent({}), null);
    assert.equal(validateExecutionEvent({ id: "1" }), null);
    assert.equal(validateExecutionEvent({ id: "1", execution_id: "ex-1" }), null);
  });
});

describe("Chain of Thought & Secret Sanitization", () => {
  it("completely strips prohibited CoT and reasoning keys", () => {
    const dirty = {
      action: "click",
      thought: "I should click this button because the user needs to sign in.",
      reasoning: "Step 2 deliberation details",
      chain_of_thought: "Hidden internal thoughts",
      prompt: "System: You are an autonomous agent...",
      target: "Sign In",
    };

    const sanitized = sanitizePayload(dirty);
    assert.equal("thought" in sanitized, false);
    assert.equal("reasoning" in sanitized, false);
    assert.equal("chain_of_thought" in sanitized, false);
    assert.equal("prompt" in sanitized, false);
    assert.equal(sanitized.action, "click");
    assert.equal(sanitized.target, "Sign In");
  });

  it("masks passwords, tokens, and authorization headers", () => {
    assert.equal(
      sanitizeText("type password: SecretPassword123!"),
      "Entered password"
    );
    assert.equal(
      sanitizeText("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"),
      "Authorization: Bearer [hidden]"
    );
    assert.equal(
      sanitizeText("token=abc123secret"),
      "token: [hidden]"
    );
  });

  it("strips raw CSS selectors and XPath queries", () => {
    assert.equal(
      sanitizeText("button[data-testid='submit-btn']"),
      ""
    );
    assert.equal(
      sanitizeText("//div[@id='content']/button[1]"),
      ""
    );
  });

  it("preserves web URLs and Supabase storage URLs", () => {
    assert.equal(
      sanitizeText("https://zmbhiudolgnlccdqicas.supabase.co/storage/v1/object/public/kova-screenshots/executions/123/shot.jpg"),
      "https://zmbhiudolgnlccdqicas.supabase.co/storage/v1/object/public/kova-screenshots/executions/123/shot.jpg"
    );
    assert.equal(
      sanitizeText("http://localhost:3000/dashboard"),
      "http://localhost:3000/dashboard"
    );
  });

  it("preserves base64 screenshot data URIs even with slash sequences", () => {
    const dataUri = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD//gA7Q1JFQVRPUg==";
    assert.equal(sanitizeText(dataUri), dataUri);
  });
});

describe("Activity Mapping and Action Collapsing", () => {
  it("collapses sequential action.started and action.completed pairs", () => {
    const events: ExecutionEvent[] = [
      {
        id: "ev-1",
        executionId: "ex-1",
        eventType: "action.started",
        payload: { action: "click", target: "Sign in" },
        createdAt: "2026-09-16T10:00:00Z",
      },
      {
        id: "ev-2",
        executionId: "ex-1",
        eventType: "action.completed",
        payload: { action: "click", target: "Sign in" },
        createdAt: "2026-09-16T10:00:02Z",
      },
    ];

    const activities = mapExecutionEvents(events);
    // Should collapse into 1 activity
    assert.equal(activities.length, 1);
    assert.equal(activities[0].label, "Clicked Sign in");
    assert.equal(activities[0].status, "completed");
  });

  it("collapses verification started and passed pairs", () => {
    const events: ExecutionEvent[] = [
      {
        id: "ev-v1",
        executionId: "ex-1",
        eventType: "verification.started",
        payload: { target: "Quiz summary" },
        createdAt: "2026-09-16T10:01:00Z",
      },
      {
        id: "ev-v2",
        executionId: "ex-1",
        eventType: "verification.passed",
        payload: { target: "Quiz summary" },
        createdAt: "2026-09-16T10:01:03Z",
      },
    ];

    const activities = mapExecutionEvents(events);
    assert.equal(activities.length, 1);
    assert.equal(activities[0].label, "Quiz summary verified");
    assert.equal(activities[0].status, "completed");
  });

  it("maps credential usage without leaking secret details", () => {
    const event: ExecutionEvent = {
      id: "ev-c1",
      executionId: "ex-1",
      eventType: "credential_used",
      payload: { name: "Student Account", email: "student@test.com", password: "secret" },
      createdAt: "2026-09-16T10:00:00Z",
    };

    const activity = mapExecutionEvent(event);
    assert.equal(activity.label, "Using Student Account");
    assert.equal(activity.icon, "key");
  });

  it("deduplicates events by event ID", () => {
    const events: ExecutionEvent[] = [
      {
        id: "dup-1",
        executionId: "ex-1",
        eventType: "action.started",
        payload: { action: "navigate" },
        createdAt: "2026-09-16T10:00:00Z",
      },
      {
        id: "dup-1",
        executionId: "ex-1",
        eventType: "action.started",
        payload: { action: "navigate" },
        createdAt: "2026-09-16T10:00:00Z",
      },
    ];

    const unique = deduplicateEvents(events);
    assert.equal(unique.length, 1);
  });

  it("transitions all actions to past state when mission is completed and browser is closed", () => {
    const events: ExecutionEvent[] = [
      {
        id: "ev-1",
        executionId: "ex-1",
        eventType: "execution.started",
        payload: {},
        createdAt: "2026-09-16T10:00:00Z",
      },
      {
        id: "ev-2",
        executionId: "ex-1",
        eventType: "action.started",
        payload: { action: "click", target: "Submit" },
        createdAt: "2026-09-16T10:00:01Z",
      },
      {
        id: "ev-3",
        executionId: "ex-1",
        eventType: "verification.started",
        payload: {},
        createdAt: "2026-09-16T10:00:02Z",
      },
      {
        id: "ev-4",
        executionId: "ex-1",
        eventType: "browser.closed",
        payload: {},
        createdAt: "2026-09-16T10:00:03Z",
      },
      {
        id: "ev-5",
        executionId: "ex-1",
        eventType: "execution.completed",
        payload: {},
        createdAt: "2026-09-16T10:00:04Z",
      },
    ];

    const activities = mapExecutionEvents(events);
    // None should be active
    const activeItems = activities.filter((a) => a.status === "active");
    assert.equal(activeItems.length, 0);

    // Kova started working should be completed
    assert.equal(activities[0].status, "completed");
    assert.equal(activities[0].label, "Kova started working");

    // Action should be completed
    assert.equal(activities[1].status, "completed");
    assert.equal(activities[1].label, "Clicked Submit");

    // Verification should be completed
    assert.equal(activities[2].status, "completed");
    assert.equal(activities[2].label, "Verification completed");
  });

  it("maps agent loop events into concise operational activities", () => {
    const events: ExecutionEvent[] = [
      {
        id: "ag-1",
        executionId: "ex-ag",
        eventType: "agent.goal_interpreted",
        payload: { goal: "Test password recovery" },
        createdAt: "2026-09-16T10:00:00Z",
      },
      {
        id: "ag-2",
        executionId: "ex-ag",
        eventType: "agent.email_created",
        payload: { address: "temp-123@test.mail" },
        createdAt: "2026-09-16T10:00:01Z",
      },
      {
        id: "ag-3",
        executionId: "ex-ag",
        eventType: "agent.action_proposed",
        payload: { action: "click", reason: "Open password recovery flow" },
        createdAt: "2026-09-16T10:00:02Z",
      },
      {
        id: "ag-4",
        executionId: "ex-ag",
        eventType: "agent.email_received",
        payload: { subject: "Reset your password" },
        createdAt: "2026-09-16T10:00:03Z",
      },
      {
        id: "ag-5",
        executionId: "ex-ag",
        eventType: "agent.verification_proposed",
        payload: { basis: "application confirmed the password change" },
        createdAt: "2026-09-16T10:00:04Z",
      },
    ];

    const activities = mapExecutionEvents(events);
    assert.equal(activities.length, 5);
    assert.equal(activities[0].label, "Objective: Test password recovery");
    assert.equal(activities[0].status, "completed");
    assert.equal(activities[1].label, "Created temporary identity: temp-123@test.mail");
    assert.equal(activities[1].status, "completed");
    assert.equal(activities[2].label, "Open password recovery flow");
    assert.equal(activities[3].label, "Received email: Reset your password");
    assert.equal(activities[3].status, "completed");
    assert.equal(activities[4].label, "Verification: application confirmed the password change");
    assert.equal(activities[4].status, "completed");
  });
});

