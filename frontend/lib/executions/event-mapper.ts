import type { ExecutionEvent, ActivityItem } from "@/lib/types";

/**
 * Event Sanitization & Activity Mapping Engine
 *
 * Strict Rules:
 * 1. NEVER expose agent chain-of-thought, reasoning, or prompts.
 * 2. NEVER expose passwords, credentials, tokens, or auth headers.
 * 3. NEVER expose raw CSS selectors, XPath, coordinates, or DOM dumps.
 * 4. Validate and deduplicate all incoming events.
 * 5. Collapse noisy action pairs into concise human-readable activities.
 */

const NOISY_EVENT_TYPES = new Set([
  "mouse.moved",
  "mouse.down",
  "mouse.up",
  "element.inspected",
  "scroll.ticked",
  "dom.mutated",
  "heartbeat",
  "telemetry.ping",
  "telemetry.metric",
]);

const PROHIBITED_COT_KEYS = new Set([
  "thought",
  "thoughts",
  "reasoning",
  "deliberation",
  "chain_of_thought",
  "hidden_planning",
  "planning",
  "model_context",
  "raw_prompt",
  "prompt",
  "model_output",
]);

/**
 * Validates and normalizes raw SSE / API payload into a typed ExecutionEvent.
 * Returns null if the event structure is malformed.
 */
export function validateExecutionEvent(raw: unknown): ExecutionEvent | null {
  if (!raw || typeof raw !== "object") return null;

  const record = raw as Record<string, unknown>;

  const id = typeof record.id === "string" ? record.id : undefined;
  const executionId =
    typeof record.execution_id === "string"
      ? record.execution_id
      : typeof record.executionId === "string"
      ? record.executionId
      : undefined;
  const eventType =
    typeof record.event_type === "string"
      ? record.event_type
      : typeof record.eventType === "string"
      ? record.eventType
      : undefined;
  const createdAt =
    typeof record.created_at === "string"
      ? record.created_at
      : typeof record.createdAt === "string"
      ? record.createdAt
      : new Date().toISOString();

  if (!id || !executionId || !eventType) {
    return null;
  }

  const rawPayload =
    typeof record.payload === "object" && record.payload !== null
      ? (record.payload as Record<string, unknown>)
      : {};

  const sanitizedPayload = sanitizePayload(rawPayload);

  return {
    id,
    executionId,
    eventType,
    payload: sanitizedPayload,
    createdAt,
  };
}

/**
 * Recursively strips CoT fields, credentials, and technical selectors from payload.
 */
export function sanitizePayload(
  payload: Record<string, unknown>
): Record<string, unknown> {
  const clean: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(payload)) {
    // Strip Chain of Thought & reasoning keys
    if (PROHIBITED_COT_KEYS.has(key.toLowerCase())) {
      continue;
    }

    const lowerKey = key.toLowerCase();
    if (
      lowerKey === "screenshot" ||
      lowerKey === "screenshot_url" ||
      lowerKey === "url" ||
      lowerKey === "storage_key" ||
      lowerKey === "final_url"
    ) {
      clean[key] = value;
    } else if (typeof value === "string") {
      clean[key] = sanitizeText(value);
    } else if (typeof value === "object" && value !== null && !Array.isArray(value)) {
      clean[key] = sanitizePayload(value as Record<string, unknown>);
    } else if (Array.isArray(value)) {
      clean[key] = value.map((item) =>
        typeof item === "object" && item !== null
          ? sanitizePayload(item as Record<string, unknown>)
          : typeof item === "string"
          ? sanitizeText(item)
          : item
      );
    } else {
      clean[key] = value;
    }
  }

  return clean;
}

/**
 * Strips secrets, passwords, tokens, selectors, and XPath from strings.
 */
export function sanitizeText(raw: string): string {
  if (!raw) return "";

  // Preserve data URIs and full web URLs without mangling
  if (raw.startsWith("data:image/") || raw.startsWith("http://") || raw.startsWith("https://")) {
    return raw;
  }

  let cleaned = raw;

  // Strip XPath expressions (e.g. //div[@id='content']/button[1]) not preceded by a URL protocol
  cleaned = cleaned.replace(/(?<!:)\/\/[^\s]+/g, "");

  // Strip CSS attribute selectors (e.g. button[data-testid="..."])
  cleaned = cleaned.replace(/([#.]?[a-zA-Z0-9_-]+)?\[[^\]]+\]/g, "");

  // Mask passwords & tokens
  cleaned = cleaned.replace(/password[:=]\s*[^\s,;]+/gi, "password: [hidden]");
  cleaned = cleaned.replace(/token[:=]\s*[^\s,;]+/gi, "token: [hidden]");
  cleaned = cleaned.replace(/bearer\s+[a-zA-Z0-9_\-\.]+/gi, "Bearer [hidden]");
  cleaned = cleaned.replace(/secret[:=]\s*[^\s,;]+/gi, "secret: [hidden]");
  cleaned = cleaned.replace(/api[-_]?key[:=]\s*[^\s,;]+/gi, "api_key: [hidden]");

  // Mask sensitive action text
  if (/type.*password/i.test(cleaned) || /enter.*password/i.test(cleaned)) {
    return "Entered password";
  }

  // Remove potential raw JSON dumps or stack traces
  if (cleaned.startsWith("{") && cleaned.endsWith("}")) {
    try {
      const parsed = JSON.parse(cleaned);
      if (parsed.message) return sanitizeText(String(parsed.message));
      if (parsed.error) return sanitizeText(String(parsed.error));
      return "Processed step";
    } catch {
      return "Processed step";
    }
  }

  const trimmed = cleaned.trim().replace(/\s+/g, " ");
  return trimmed.slice(0, 140);
}

/**
 * Human-friendly activity labels and icons by event type.
 */
const eventMessageMap: Record<
  string,
  (payload: Record<string, unknown>) => { label: string; icon: string }
> = {
  "execution.created": () => ({
    label: "Preparing execution",
    icon: "play_circle",
  }),
  "execution.queued": () => ({
    label: "Waiting to start",
    icon: "schedule",
  }),
  "execution.started": () => ({
    label: "Kova started working",
    icon: "play_arrow",
  }),
  "execution.completed": () => ({
    label: "Mission completed",
    icon: "check_circle",
  }),
  "execution.failed": (p) => {
    const rawReason = typeof p.reason === "string" ? p.reason : "Execution failed";
    return {
      label: sanitizeText(rawReason) || "Execution failed",
      icon: "error",
    };
  },
  "execution.timeout": () => ({
    label: "Execution timed out",
    icon: "schedule",
  }),
  "execution.cancelled": () => ({
    label: "Execution cancelled",
    icon: "cancel",
  }),
  "browser.started": () => ({
    label: "Browser ready",
    icon: "laptop",
  }),
  "page.loaded": (p) => {
    const url = typeof p.url === "string" ? p.url : "";
    let target = "page";
    if (url) {
      try {
        target = new URL(url).hostname;
      } catch {
        target = "page";
      }
    }
    return {
      label: `Opened ${target}`,
      icon: "open_in_new",
    };
  },
  "credential_used": (p) => {
    const name = typeof p.name === "string" ? p.name : "Test Account";
    return {
      label: `Using ${sanitizeText(name)}`,
      icon: "key",
    };
  },
  "action.started": (p) => {
    const action = typeof p.action === "string" ? p.action : "action";
    const target = typeof p.target === "string" ? sanitizeText(p.target) : "";

    if (action === "navigate" || action === "goto") {
      return { label: "Opening page", icon: "open_in_new" };
    }
    if (action === "click") {
      return { label: target ? `Clicking ${target}` : "Clicking element", icon: "touch_app" };
    }
    if (action === "type" || action === "fill") {
      return { label: "Entering information", icon: "edit" };
    }

    const desc = typeof p.description === "string" ? sanitizeText(p.description) : "";
    return {
      label: desc || "Performing action",
      icon: "touch_app",
    };
  },
  "action.completed": (p) => {
    const action = typeof p.action === "string" ? p.action : "action";
    const target = typeof p.target === "string" ? sanitizeText(p.target) : "";

    if (action === "navigate" || action === "goto") {
      return { label: "Opened page", icon: "open_in_new" };
    }
    if (action === "click") {
      return { label: target ? `Clicked ${target}` : "Clicked element", icon: "check" };
    }
    if (action === "type" || action === "fill") {
      return { label: "Information entered", icon: "check" };
    }

    const desc = typeof p.description === "string" ? sanitizeText(p.description) : "";
    return {
      label: desc || "Action completed",
      icon: "check",
    };
  },
  "agent.observed": () => ({
    label: "Observing interface",
    icon: "visibility",
  }),
  "observation": () => ({
    label: "Observed page state",
    icon: "visibility",
  }),
  "browser.closed": () => ({
    label: "Browser closed",
    icon: "laptop",
  }),
  "browser.screenshot": () => ({
    label: "Browser snapshot",
    icon: "photo_camera",
  }),
  "verification.started": (p) => {
    const target = typeof p.target === "string" ? sanitizeText(p.target) : "";
    return {
      label: target ? `Checking ${target}` : "Checking result",
      icon: "fact_check",
    };
  },
  "verification.completed": (p) => {
    const passed = p.passed !== false;
    return {
      label: passed ? "Verification completed" : "Verification finished",
      icon: passed ? "verified" : "cancel",
    };
  },
  "verification.passed": (p) => {
    const target = typeof p.target === "string" ? sanitizeText(p.target) : "";
    return {
      label: target ? `${target} verified` : "Result verified",
      icon: "verified",
    };
  },
  "verification.failed": (p) => {
    const target = typeof p.target === "string" ? sanitizeText(p.target) : "";
    return {
      label: target ? `${target} could not be verified` : "Result could not be verified",
      icon: "cancel",
    };
  },
  "recovery.started": () => ({
    label: "Trying another path",
    icon: "replay",
  }),
  "evidence.capture.started": () => ({
    label: "Capturing proof",
    icon: "photo_camera",
  }),
  "evidence.captured": (p) => {
    const title = typeof p.title === "string" ? sanitizeText(p.title) : "";
    const type = typeof p.type === "string" ? p.type : "";
    if (type === "VERIFICATION") {
      return { label: title || "Verification recorded", icon: "verified" };
    }
    return { label: title || "Evidence captured", icon: "photo_library" };
  },
  "evidence.failed": () => ({
    label: "Evidence capture skipped",
    icon: "warning",
  }),
  "agent.goal_interpreted": (p) => {
    const goal = typeof p.goal === "string" ? sanitizeText(p.goal) : "Understood objective";
    return {
      label: goal ? `Objective: ${goal}` : "Understood objective",
      icon: "psychology",
    };
  },
  "agent.plan_created": (p) => {
    const steps = typeof p.steps === "number" ? p.steps : 0;
    return {
      label: steps ? `Formulated plan (${steps} steps)` : "Formulated journey plan",
      icon: "alt_route",
    };
  },
  "agent.observation_created": (p) => {
    const turn = typeof p.turn === "number" ? ` (turn ${p.turn})` : "";
    return {
      label: `Observed interface state${turn}`,
      icon: "visibility",
    };
  },
  "agent.action_proposed": (p) => {
    const action = typeof p.action === "string" ? p.action : "action";
    const reason = typeof p.reason === "string" ? sanitizeText(p.reason) : "";
    return {
      label: reason || `Proposing ${action}`,
      icon: "bolt",
    };
  },
  "agent.action_validated": (p) => {
    const action = typeof p.action === "string" ? p.action : "action";
    return {
      label: `Validated ${action} safety`,
      icon: "security",
    };
  },
  "agent.state_changed": (p) => {
    const action = typeof p.action === "string" ? p.action : "action";
    return {
      label: `Executed ${action} successfully`,
      icon: "check_circle",
    };
  },
  "agent.replan_triggered": (p) => {
    const reason = typeof p.reason === "string" ? sanitizeText(p.reason) : "Adapting plan";
    return {
      label: `Replanning: ${reason}`,
      icon: "sync",
    };
  },
  "agent.recovery_proposed": (p) => {
    const detail = typeof p.detail === "string" ? sanitizeText(p.detail) : "Trying alternative strategy";
    return {
      label: `Recovery: ${detail}`,
      icon: "replay",
    };
  },
  "agent.email_created": (p) => {
    const address = typeof p.address === "string" ? sanitizeText(p.address) : "";
    return {
      label: address ? `Created temporary identity: ${address}` : "Created temporary identity",
      icon: "mail",
    };
  },
  "agent.email_received": (p) => {
    const subject = typeof p.subject === "string" ? sanitizeText(p.subject) : "";
    return {
      label: subject ? `Received email: ${subject}` : "Received external email",
      icon: "mark_email_read",
    };
  },
  "agent.email_link_selected": (p) => {
    const path = typeof p.path === "string" ? sanitizeText(p.path) : "";
    return {
      label: path ? `Opening verified link: ${path}` : "Opening verified email link",
      icon: "link",
    };
  },
  "agent.verification_proposed": (p) => {
    const basis = typeof p.basis === "string" ? sanitizeText(p.basis) : "Verifying objective";
    return {
      label: `Verification: ${basis}`,
      icon: "fact_check",
    };
  },
  "agent.human_input_required": (p) => {
    const reason = typeof p.reason === "string" ? sanitizeText(p.reason) : "Human takeover required";
    return {
      label: `Action required: ${reason}`,
      icon: "pan_tool",
    };
  },
};

function inferStatusFromEventType(eventType: string): ActivityItem["status"] {
  if (
    eventType.endsWith(".completed") ||
    eventType.endsWith(".passed") ||
    eventType === "page.loaded" ||
    eventType === "browser.started" ||
    eventType === "browser.closed" ||
    eventType === "execution.started" ||
    eventType === "observation" ||
    eventType === "browser.screenshot" ||
    eventType === "evidence.captured" ||
    eventType === "agent.goal_interpreted" ||
    eventType === "agent.plan_created" ||
    eventType === "agent.state_changed" ||
    eventType === "agent.email_created" ||
    eventType === "agent.email_received" ||
    eventType === "agent.email_link_selected" ||
    eventType === "agent.verification_proposed"
  ) {
    return "completed";
  }
  if (eventType.endsWith(".failed") || eventType.endsWith(".timeout") || eventType === "agent.failed") {
    return "failed";
  }
  if (
    eventType.endsWith(".started") ||
    eventType === "agent.observed" ||
    eventType === "agent.observation_created" ||
    eventType === "agent.action_proposed" ||
    eventType === "agent.action_validated" ||
    eventType === "agent.replan_triggered" ||
    eventType === "agent.recovery_proposed" ||
    eventType === "agent.human_input_required" ||
    eventType === "recovery.started"
  ) {
    return "active";
  }
  return "pending";
}

function formatEventType(eventType: string): string {
  return sanitizeText(
    eventType
      .split(".")
      .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
      .join(" ")
  );
}

/**
 * Maps an ExecutionEvent into a presentation-safe ActivityItem.
 */
export function mapExecutionEvent(event: ExecutionEvent): ActivityItem {
  const mapper = eventMessageMap[event.eventType];
  const { label, icon } = mapper
    ? mapper(event.payload ?? {})
    : { label: formatEventType(event.eventType), icon: "info" };

  return {
    id: event.id,
    label,
    status: inferStatusFromEventType(event.eventType),
    timestamp: event.createdAt,
    icon,
  };
}

/**
 * Deduplicates events by monotonic or UUID event id.
 */
export function deduplicateEvents(events: ExecutionEvent[]): ExecutionEvent[] {
  const seen = new Set<string>();
  const unique: ExecutionEvent[] = [];

  for (const ev of events) {
    if (!ev || !ev.id) continue;
    if (!seen.has(ev.id)) {
      seen.add(ev.id);
      unique.push(ev);
    }
  }

  return unique;
}

/**
 * Maps and collapses low-level execution events into concise, non-redundant human activities.
 * Sequential pairs like (action.started -> action.completed) are collapsed into a single completed step.
 */
export function mapExecutionEvents(events: ExecutionEvent[]): ActivityItem[] {
  // Deduplicate and filter noisy browser telemetry
  const validEvents = deduplicateEvents(events).filter(
    (ev) => !NOISY_EVENT_TYPES.has(ev.eventType)
  );

  const activities: ActivityItem[] = [];

  for (let i = 0; i < validEvents.length; i++) {
    const current = validEvents[i];
    const next = validEvents[i + 1];

    // Collapse (action.started + action.completed) pairs
    if (
      current.eventType === "action.started" &&
      next &&
      next.eventType === "action.completed"
    ) {
      // Use the completed event's mapped representation
      activities.push(mapExecutionEvent(next));
      i++; // Skip the completed event since it's merged
      continue;
    }

    // Collapse (verification.started + verification.passed/failed/completed) pairs
    if (
      current.eventType === "verification.started" &&
      next &&
      (next.eventType === "verification.passed" ||
        next.eventType === "verification.failed" ||
        next.eventType === "verification.completed")
    ) {
      activities.push(mapExecutionEvent(next));
      i++;
      continue;
    }

    activities.push(mapExecutionEvent(current));
  }

  // Check if execution has reached a terminal or closed state
  const isTerminal = validEvents.some((ev) =>
    ev.eventType === "execution.completed" ||
    ev.eventType === "execution.failed" ||
    ev.eventType === "execution.timeout" ||
    ev.eventType === "execution.cancelled" ||
    ev.eventType === "browser.closed"
  );

  // If terminal, no activity should remain active.
  // If running, only the very last active item should remain active.
  const lastActiveIndex = isTerminal
    ? -1
    : activities.map((a) => a.status).lastIndexOf("active");

  return activities.map((item, index) => {
    if (item.status === "active" && index !== lastActiveIndex) {
      let pastLabel = item.label;
      if (pastLabel === "Performing action") pastLabel = "Action performed";
      else if (pastLabel === "Checking result") pastLabel = "Verification completed";
      else if (pastLabel === "Opening page") pastLabel = "Opened page";
      else if (pastLabel === "Observing interface") pastLabel = "Interface observed";
      else if (pastLabel.startsWith("Clicking ")) pastLabel = pastLabel.replace("Clicking ", "Clicked ");
      else if (pastLabel.startsWith("Entering ")) pastLabel = pastLabel.replace("Entering ", "Entered ");

      return {
        ...item,
        status: "completed",
        label: pastLabel,
        icon: item.icon === "progress_activity" || !item.icon ? "check_circle" : item.icon,
      };
    }
    return item;
  });
}
