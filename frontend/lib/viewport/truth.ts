/**
 * Server-confirmed viewport truth.
 *
 * Every field here is derived from a message the server actually sent. The UI
 * must render these values instead of optimistic guesses: a takeover is only
 * "confirmed" once the server reports HUMAN_CONTROL, a pause only once the
 * server reports PAUSED, and a frame is only "masked" when the server tagged
 * it as masked.
 */

export type ServerControl =
  | "agent"
  | "agent_pausing"
  | "paused"
  | "human_pending"
  | "human"
  | "reconciling"
  | "waiting_user"
  | "resume_pending"
  | "stopped";

export type HandoffPhase = "idle" | "requesting" | "pending" | "confirmed" | "failed";

export type MaskingStatus = "masked" | "off" | "unknown";

export interface ViewportQuality {
  fps: number | null;
  unacked: number;
  dropped: number;
  rttMs: number | null;
}

export interface ViewportTruth {
  control: ServerControl;
  handoff: HandoffPhase;
  handoffError: string | null;
  masking: MaskingStatus;
  lastFrameSeq: number | null;
  lastFrameAt: number | null;
  lastAckedSeq: number | null;
  quality: ViewportQuality;
}

export interface ServerMessage {
  type?: string;
  control?: string;
  state?: string;
  seq?: number | string;
  masking?: string;
  ts?: number | string;
  reason?: string;
  fps?: number;
  unacked?: number;
  dropped?: number;
  rtt_ms?: number;
  lease_id?: string | null;
  generation?: number;
}

const CONTROL_VALUES: readonly ServerControl[] = [
  "agent",
  "agent_pausing",
  "paused",
  "human_pending",
  "human",
  "reconciling",
  "waiting_user",
  "resume_pending",
  "stopped",
];

const MASKING_VALUES: readonly MaskingStatus[] = ["masked", "off", "unknown"];

export function initialViewportTruth(): ViewportTruth {
  return {
    control: "agent",
    handoff: "idle",
    handoffError: null,
    masking: "unknown",
    lastFrameSeq: null,
    lastFrameAt: null,
    lastAckedSeq: null,
    quality: { fps: null, unacked: 0, dropped: 0, rttMs: null },
  };
}

export function normalizeControl(value: unknown): ServerControl | null {
  return typeof value === "string" && (CONTROL_VALUES as readonly string[]).includes(value)
    ? (value as ServerControl)
    : null;
}

export function normalizeMasking(value: unknown): MaskingStatus | null {
  return typeof value === "string" && (MASKING_VALUES as readonly string[]).includes(value)
    ? (value as MaskingStatus)
    : null;
}

/** User asked to take over; nothing is confirmed yet. */
export function markTakeoverRequested(state: ViewportTruth): ViewportTruth {
  return { ...state, handoff: "requesting", handoffError: null };
}

/** User dismissed the takeover prompt; no server round-trip is pending. */
export function markTakeoverDeclined(state: ViewportTruth): ViewportTruth {
  return { ...state, handoff: "idle", handoffError: null };
}

/** User handed control back; the server must still confirm the agent resume. */
export function markReturnRequested(state: ViewportTruth): ViewportTruth {
  return { ...state, handoff: "requesting", handoffError: null };
}

/**
 * A new frame header arrived. Frames must be strictly newer than the last one;
 * stale/duplicate seq values are ignored so an out-of-order delivery can never
 * repaint the canvas with an older page.
 */
export function applyFrame(
  state: ViewportTruth,
  frame: { seq?: unknown; masking?: unknown; ts?: unknown }
): ViewportTruth {
  const seq = typeof frame.seq === "number" ? frame.seq : Number(frame.seq);
  if (!Number.isFinite(seq)) return state;
  if (state.lastFrameSeq !== null && seq <= state.lastFrameSeq) return state;

  const masking = normalizeMasking(frame.masking) ?? state.masking;
  const ts = typeof frame.ts === "number" ? frame.ts : Number(frame.ts);

  return {
    ...state,
    lastFrameSeq: seq,
    lastFrameAt: Number.isFinite(ts) ? ts * 1000 : Date.now(),
    masking,
  };
}

/** Client-side ack bookkeeping, mirroring what the server relay records. */
export function markFrameAcked(state: ViewportTruth, seq: number): ViewportTruth {
  if (!Number.isFinite(seq)) return state;
  if (state.lastAckedSeq !== null && seq <= state.lastAckedSeq) return state;
  return { ...state, lastAckedSeq: seq };
}

export function resetViewportTruth(state: ViewportTruth): ViewportTruth {
  return { ...initialViewportTruth(), control: state.control === "stopped" ? "stopped" : "agent" };
}

export function applyServerMessage(state: ViewportTruth, msg: ServerMessage): ViewportTruth {
  if (!msg || typeof msg !== "object") return state;

  switch (msg.type) {
    case "frame": {
      return applyFrame(state, msg);
    }
    case "masking_status": {
      const masking = normalizeMasking(msg.masking);
      return masking ? { ...state, masking } : state;
    }
    case "connection_quality": {
      return {
        ...state,
        quality: {
          fps: typeof msg.fps === "number" ? msg.fps : state.quality.fps,
          unacked: typeof msg.unacked === "number" ? msg.unacked : state.quality.unacked,
          dropped: typeof msg.dropped === "number" ? msg.dropped : state.quality.dropped,
          rttMs: typeof msg.rtt_ms === "number" ? msg.rtt_ms : state.quality.rttMs,
        },
      };
    }
    case "control_changed": {
      const control = normalizeControl(msg.control);
      if (!control) return state;
      return {
        ...state,
        control,
        handoff:
          control === "human"
            ? "confirmed"
            : state.handoff === "confirmed"
            ? "idle"
            : state.handoff,
        handoffError: control === "human" ? null : state.handoffError,
      };
    }
    case "takeover_granted": {
      // The server grants the lease while the browser is still QUIESCING.
      const control = normalizeControl(msg.control) ?? "human_pending";
      return {
        ...state,
        control,
        handoff: control === "human" ? "confirmed" : "pending",
        handoffError: null,
      };
    }
    case "takeover_rejected": {
      return {
        ...state,
        control: "agent",
        handoff: "failed",
        handoffError: msg.reason || "Browser takeover unavailable",
      };
    }
    case "control_error":
    case "interaction_rejected": {
      return {
        ...state,
        handoff: "failed",
        handoffError: msg.reason || "Control request failed",
      };
    }
    case "pause_requested": {
      const control = normalizeControl(msg.control) ?? "agent_pausing";
      return { ...state, control };
    }
    case "resume_requested": {
      const control = normalizeControl(msg.control) ?? "resume_pending";
      return { ...state, control };
    }
    case "lease_expired": {
      return {
        ...state,
        control: "agent",
        handoff: state.handoff === "failed" ? "failed" : "idle",
        handoffError: msg.reason || null,
      };
    }
    case "state": {
      const control = normalizeControl(msg.control);
      return control ? { ...state, control } : state;
    }
    default:
      return state;
  }
}

export function isConfirmedHuman(state: ViewportTruth): boolean {
  return state.control === "human";
}

export function isPendingHandoff(state: ViewportTruth): boolean {
  return (
    state.handoff === "requesting" ||
    state.handoff === "pending" ||
    state.control === "human_pending" ||
    state.control === "reconciling"
  );
}

export function isAgentRunning(state: ViewportTruth): boolean {
  return state.control === "agent" || state.control === "agent_pausing";
}

export function frameAgeMs(state: ViewportTruth, now: number = Date.now()): number | null {
  return state.lastFrameAt === null ? null : Math.max(0, now - state.lastFrameAt);
}

export function isFrameStale(
  state: ViewportTruth,
  now: number = Date.now(),
  maxAgeMs = 5000
): boolean {
  const age = frameAgeMs(state, now);
  return age !== null && age > maxAgeMs;
}

/**
 * Honesty rules for the masking banner. Only a server "masked" tag may claim
 * that sensitive fields are hidden; "off" and "unknown" are both exposed states
 * and must be labelled as such.
 */
export function maskingCopy(masking: MaskingStatus): {
  label: string;
  tone: "protected" | "exposed" | "unknown";
} {
  if (masking === "masked") {
    return { label: "Sensitive fields masked", tone: "protected" };
  }
  if (masking === "off") {
    return { label: "Sensitive fields NOT masked", tone: "exposed" };
  }
  return { label: "Masking status unknown", tone: "unknown" };
}
