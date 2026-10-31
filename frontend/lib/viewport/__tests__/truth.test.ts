import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  applyFrame,
  applyServerMessage,
  frameAgeMs,
  initialViewportTruth,
  isConfirmedHuman,
  isFrameStale,
  isPendingHandoff,
  markFrameAcked,
  markTakeoverRequested,
  maskingCopy,
  resetViewportTruth,
} from "../truth";
import type { ViewportTruth } from "../truth";

function withMessages(...messages: Parameters<typeof applyServerMessage>[1][]): ViewportTruth {
  return messages.reduce(applyServerMessage, initialViewportTruth());
}

describe("control handoff truth", () => {
  it("stays pending while the browser is still quiescing", () => {
    const truth = withMessages(
      { type: "takeover_granted", control: "human_pending", state: "QUIESCING" }
    );

    assert.equal(truth.handoff, "pending");
    assert.equal(truth.control, "human_pending");
    assert.equal(isConfirmedHuman(truth), false);
    assert.equal(isPendingHandoff(truth), true);
  });

  it("only confirms human control when the server reports HUMAN_CONTROL", () => {
    const pending = withMessages(
      { type: "takeover_granted", control: "human_pending" }
    );
    assert.equal(isConfirmedHuman(pending), false);

    const confirmed = applyServerMessage(pending, {
      type: "control_changed",
      control: "human",
    });
    assert.equal(confirmed.handoff, "confirmed");
    assert.equal(isConfirmedHuman(confirmed), true);
  });

  it("reverts to agent and surfaces the reason when takeover is rejected", () => {
    const requested = markTakeoverRequested(initialViewportTruth());
    assert.equal(requested.handoff, "requesting");

    const rejected = applyServerMessage(requested, {
      type: "takeover_rejected",
      reason: "Another operator holds the lease",
    });

    assert.equal(rejected.handoff, "failed");
    assert.equal(rejected.control, "agent");
    assert.equal(isConfirmedHuman(rejected), false);
    assert.equal(rejected.handoffError, "Another operator holds the lease");
  });

  it("keeps paused pending until the server confirms PAUSED", () => {
    const requested = applyServerMessage(initialViewportTruth(), {
      type: "pause_requested",
      control: "agent_pausing",
    });
    assert.equal(requested.control, "agent_pausing");

    const confirmed = applyServerMessage(requested, {
      type: "control_changed",
      control: "paused",
    });
    assert.equal(confirmed.control, "paused");
  });

  it("drops human control when the lease expires", () => {
    const human = withMessages(
      { type: "takeover_granted", control: "human_pending" },
      { type: "control_changed", control: "human" }
    );
    assert.equal(isConfirmedHuman(human), true);

    const expired = applyServerMessage(human, { type: "lease_expired" });
    assert.equal(isConfirmedHuman(expired), false);
    assert.equal(expired.control, "agent");
  });

  it("ignores unknown control values instead of guessing", () => {
    const truth = withMessages({ type: "control_changed", control: "yolo" });
    assert.equal(truth.control, "agent");
    assert.equal(truth.handoff, "idle");
  });
});

describe("frame pipeline truth", () => {
  it("accepts only strictly newer frames", () => {
    const first = applyFrame(initialViewportTruth(), { seq: 4, masking: "masked", ts: 1 });
    assert.equal(first.lastFrameSeq, 4);

    const stale = applyFrame(first, { seq: 3, masking: "off", ts: 2 });
    assert.equal(stale.lastFrameSeq, 4);
    assert.equal(stale.masking, "masked");

    const duplicate = applyFrame(first, { seq: 4, masking: "off", ts: 2 });
    assert.equal(duplicate.masking, "masked");

    const newer = applyFrame(first, { seq: 5, masking: "masked", ts: 3 });
    assert.equal(newer.lastFrameSeq, 5);
  });

  it("never claims masked without a server masked tag", () => {
    const unknown = applyFrame(initialViewportTruth(), { seq: 1 });
    assert.equal(unknown.masking, "unknown");
    assert.equal(maskingCopy(unknown.masking).tone, "unknown");

    const exposed = applyFrame(unknown, { seq: 2, masking: "off" });
    assert.equal(exposed.masking, "off");
    assert.equal(maskingCopy(exposed.masking).tone, "exposed");

    const malformed = applyFrame(exposed, { seq: 3, masking: "yes" });
    assert.equal(malformed.masking, "off");
  });

  it("tracks frame age and staleness", () => {
    const truth = applyFrame(initialViewportTruth(), { seq: 1, ts: 100 });
    assert.equal(frameAgeMs(truth, 100_000), 0);
    assert.equal(isFrameStale(truth, 100_000, 5000), false);
    assert.equal(frameAgeMs(truth, 101_000), 1000);
    assert.equal(isFrameStale(truth, 101_100, 5000), false);
    assert.equal(isFrameStale(truth, 106_500, 5000), true);
  });

  it("resets frame continuity on reconnect", () => {
    const truth = applyFrame(initialViewportTruth(), { seq: 9, masking: "masked" });
    const reset = resetViewportTruth(truth);

    assert.equal(reset.lastFrameSeq, null);
    assert.equal(reset.lastFrameAt, null);
    assert.equal(reset.masking, "unknown");
    // A frame that was already delivered before the reconnect is accepted again
    // because continuity is judged per connection.
    const replayed = applyFrame(reset, { seq: 2, masking: "masked" });
    assert.equal(replayed.lastFrameSeq, 2);
  });

  it("records acknowledged sequence numbers monotonically", () => {
    const truth = markFrameAcked(initialViewportTruth(), 10);
    assert.equal(truth.lastAckedSeq, 10);

    const older = markFrameAcked(truth, 9);
    assert.equal(older.lastAckedSeq, 10);

    const newer = markFrameAcked(truth, 12);
    assert.equal(newer.lastAckedSeq, 12);
  });

  it("mirrors server quality stats", () => {
    const truth = applyServerMessage(initialViewportTruth(), {
      type: "connection_quality",
      fps: 7.5,
      unacked: 1,
      dropped: 2,
      rtt_ms: 42.1,
    });

    assert.deepEqual(truth.quality, { fps: 7.5, unacked: 1, dropped: 2, rttMs: 42.1 });
  });
});
