/**
 * Real Exploration Service API Client.
 * Connects directly to FastAPI exploration endpoints with SSE streaming.
 * No mocked or simulated timeouts in the production flow.
 */

import type {
  ExplorationEvent,
  SuggestedMission,
  DiscoveryItem,
  AgentQuestionItem,
  ExploreState,
  CredentialRequest,
} from "@/lib/types";
import { api, getApiBaseUrl, getBrowserSessionToken } from "./client";

export interface BackendExplorationSession {
  id: string;
  user_id: string;
  project_id: string | null;
  url: string;
  goal: string | null;
  status: string;
  selected_role: string | null;
  discoveries: DiscoveryItem[];
  candidate_missions: Array<{
    id: string;
    name: string;
    title?: string;
    description?: string;
    objective: string;
    persona?: string;
    journey: string[];
    steps: string[];
    successCondition?: string | Record<string, unknown>;
    confidence?: number;
    recommended?: boolean;
  }>;
  question: {
    id: string;
    title: string;
    description?: string;
    type: "role" | "clarification";
    options: Array<{
      id: string;
      label: string;
      description?: string;
      icon?: string;
    }>;
  } | null;
  credential_request: {
    type: "login";
    reason: string;
  } | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export function normalizeExploreStatus(status: string): ExploreState {
  const s = status.toLowerCase();
  switch (s) {
    case "created":
    case "connecting":
      return "connecting";
    case "loading":
      return "loading";
    case "validating_page":
      return "validating_page";
    case "exploring":
      return "exploring";
    case "understanding":
      return "understanding";
    case "auth_required":
      return "auth_required";
    case "authenticating":
      return "authenticating";
    case "asking":
      return "asking";
    case "discovering":
      return "discovering";
    case "planning":
      return "planning";
    case "ready":
      return "ready";
    case "executing":
      return "executing";
    case "completed":
      return "completed";
    case "failed":
      return "failed";
    case "cancelled":
      return "cancelled";
    default:
      return "connecting";
  }
}

export async function createExplorationSession(
  url: string,
  goal?: string,
  token?: string
): Promise<BackendExplorationSession> {
  return await api.post<BackendExplorationSession>(
    "/api/v1/exploration/",
    { url, goal },
    { token, timeoutMs: 60000 }
  );
}

export async function getExplorationSession(
  sessionId: string,
  token?: string
): Promise<BackendExplorationSession> {
  return await api.get<BackendExplorationSession>(
    `/api/v1/exploration/${encodeURIComponent(sessionId)}`,
    token
  );
}

export async function submitExplorationCredentials(
  sessionId: string,
  email: string,
  password: string,
  save = false,
  token?: string
): Promise<BackendExplorationSession> {
  return await api.post<BackendExplorationSession>(
    `/api/v1/exploration/${encodeURIComponent(sessionId)}/credentials`,
    { email, password, save },
    token
  );
}

export async function submitExplorationAnswer(
  sessionId: string,
  questionId: string,
  answer: string,
  token?: string
): Promise<BackendExplorationSession> {
  return await api.post<BackendExplorationSession>(
    `/api/v1/exploration/${encodeURIComponent(sessionId)}/answer`,
    { question_id: questionId, answer },
    token
  );
}

export async function cancelExplorationSession(
  sessionId: string,
  token?: string
): Promise<void> {
  await api.post(
    `/api/v1/exploration/${encodeURIComponent(sessionId)}/cancel`,
    undefined,
    token
  );
}

/**
 * Request Kova to create an account on the target site.
 * If email/password are provided, Kova uses them; otherwise it generates random credentials.
 */
export async function createExplorationAccount(
  sessionId: string,
  email?: string,
  password?: string,
  token?: string
): Promise<BackendExplorationSession> {
  return await api.post<BackendExplorationSession>(
    `/api/v1/exploration/${encodeURIComponent(sessionId)}/create-account`,
    { email, password },
    { token, timeoutMs: 120000 }
  );
}

/**
 * Navigate the browser for an active exploration (back, forward, reload).
 */
export async function navigateExploration(
  sessionId: string,
  action: "back" | "forward" | "reload",
  token?: string
): Promise<{ url: string; path: string; title: string }> {
  return await api.post(
    `/api/v1/exploration/${encodeURIComponent(sessionId)}/navigate/${action}`,
    undefined,
    token
  );
}

/**
 * Connects to live Server-Sent Events stream for an exploration session.
 */
export async function streamExplorationEvents(
  sessionId: string,
  onEvent: (event: ExplorationEvent) => void,
  signal?: AbortSignal,
  token?: string
): Promise<void> {
  const baseUrl = getApiBaseUrl();
  const streamUrl = `${baseUrl}/api/v1/exploration/${encodeURIComponent(sessionId)}/events/stream`;

  let authToken = token;
  if (!authToken && typeof window !== "undefined") {
    authToken = (await getBrowserSessionToken()) ?? undefined;
  }

  const headers: Record<string, string> = {
    Accept: "text/event-stream",
  };
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }

  try {
    const response = await fetch(streamUrl, {
      method: "GET",
      headers,
      signal,
    });

    if (!response.ok || !response.body) {
      // Fall back to polling session state if SSE unavailable
      await syncSessionState(sessionId, onEvent, token);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let currentEvent = "";
    let currentData = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split(/\r\n|\r|\n/);
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (line.startsWith("event:")) {
          currentEvent = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          currentData += line.slice(5).trim();
        } else if (line === "" && currentData) {
          try {
            const parsed = JSON.parse(currentData);
            handleStreamPayload(currentEvent, parsed, onEvent);
          } catch {
            // Ignore malformed JSON
          }
          currentEvent = "";
          currentData = "";
        }
      }
    }

    // Final sync upon stream completion
    await syncSessionState(sessionId, onEvent, token);
  } catch (err) {
    if ((err as Error).name !== "AbortError") {
      await syncSessionState(sessionId, onEvent, token);
    }
  }
}

function handleStreamPayload(
  eventType: string,
  raw: Record<string, unknown>,
  onEvent: (event: ExplorationEvent) => void
) {
  // If wrapped in SSE data payload format: { id, event_type, payload: { ... } }
  const inner =
    raw.payload && typeof raw.payload === "object" && !Array.isArray(raw.payload)
      ? (raw.payload as Record<string, unknown>)
      : raw;

  const type =
    (typeof raw.event_type === "string" ? raw.event_type : eventType) || eventType;

  if (type === "browser.screenshot" || type === "screenshot") {
    // Priority 1: Direct public URL from Supabase Storage
    const screenshotUrl =
      typeof inner.screenshot_url === "string"
        ? inner.screenshot_url
        : typeof raw.screenshot_url === "string"
        ? raw.screenshot_url
        : null;
    // Priority 2: Legacy base64 data URI
    const screenshotDataUri =
      typeof inner.screenshot === "string"
        ? inner.screenshot
        : typeof raw.screenshot === "string"
        ? raw.screenshot
        : null;
    // Priority 3: File key — construct URL via backend serving endpoint
    const screenshotKey =
      typeof inner.screenshot_key === "string"
        ? inner.screenshot_key
        : typeof raw.screenshot_key === "string"
        ? raw.screenshot_key
        : null;

    const screenshotValue = screenshotUrl || screenshotDataUri || (screenshotKey ? `${getApiBaseUrl()}/api/v1/exploration/screenshots/${screenshotKey}` : null);
    if (screenshotValue) {
      onEvent({
        type: "screenshot",
        screenshot: screenshotValue,
        url: typeof inner.url === "string" ? inner.url : undefined,
        path: typeof inner.path === "string" ? inner.path : undefined,
      });
    }
  } else if (type === "page.loaded") {
    // Extract screenshot URL (Supabase public URL preferred, fallback to key-based URL)
    const pageScreenshotUrl =
      typeof inner.screenshot_url === "string"
        ? inner.screenshot_url
        : typeof inner.screenshot_key === "string"
        ? `${getApiBaseUrl()}/api/v1/exploration/screenshots/${inner.screenshot_key}`
        : typeof inner.screenshot === "string"
        ? inner.screenshot
        : undefined;

    onEvent({
      type: "page_loaded",
      url: typeof inner.url === "string" ? inner.url : "",
      title: typeof inner.title === "string" ? inner.title : undefined,
      path: typeof inner.path === "string" ? inner.path : undefined,
      screenshot: pageScreenshotUrl,
    });
  } else if (type === "page.url_changed") {
    onEvent({
      type: "page_loaded",
      url: typeof inner.url === "string" ? inner.url : "",
      path: typeof inner.path === "string" ? inner.path : undefined,
    });
  } else if (type === "progress") {
    if (inner.activity) {
      onEvent({
        type: "progress",
        activity: inner.activity as ExplorationEvent extends { type: "progress"; activity: infer A } ? A : never,
      });
    } else if (typeof inner.message === "string") {
      onEvent({
        type: "progress",
        activity: {
          id: String(inner.id || `exp-${Date.now()}`),
          message: inner.message,
          status: (inner.status as "pending" | "active" | "completed" | "failed") || "completed",
        },
      });
    }
  } else if (type === "state_change") {
    const status =
      typeof inner.status === "string"
        ? inner.status
        : typeof raw.status === "string"
        ? raw.status
        : null;
    if (status) {
      onEvent({
        type: "state_change",
        state: normalizeExploreStatus(status),
      });
    }
  } else if (type === "auth.required") {
    const request = (inner.request || inner) as CredentialRequest;
    onEvent({
      type: "auth_required",
      request,
    });
  } else if (type === "authenticating") {
    onEvent({
      type: "state_change",
      state: "authenticating",
    });
  } else if (type === "authenticated") {
    onEvent({
      type: "state_change",
      state: "discovering",
    });
  } else if (type === "question") {
    const question = (inner.question || inner) as AgentQuestionItem;
    onEvent({
      type: "question",
      question,
    });
  } else if (type === "discovery") {
    const rawDisc = inner.discoveries || raw.discoveries;
    if (Array.isArray(rawDisc)) {
      onEvent({
        type: "discovery",
        discoveries: rawDisc as DiscoveryItem[],
      });
    }
  } else if (type === "missions") {
    const rawMissions = inner.missions || raw.missions;
    if (Array.isArray(rawMissions)) {
      onEvent({
        type: "missions",
        missions: mapCandidateMissions(rawMissions),
        recommendation: typeof inner.recommendation === "string" ? inner.recommendation : undefined,
      });
    }
  } else if (type === "ready") {
    onEvent({
      type: "state_change",
      state: "ready",
    });
  } else if (type === "exploration.failed" || type === "error" || type === "auth.failed") {
    const errorMsg =
      typeof inner.error === "string"
        ? inner.error
        : typeof raw.error === "string"
        ? raw.error
        : "Exploration failed";
    onEvent({
      type: "error",
      message: errorMsg,
    });
  }
}

function mapCandidateMissions(rawList: unknown[]): SuggestedMission[] {
  return rawList.map((item, idx) => {
    const m = item as Record<string, unknown>;
    const rawSteps = Array.isArray(m.steps) ? m.steps : (Array.isArray(m.journey) ? m.journey : []);
    return {
      id: String(m.id || `mission-${idx}`),
      title: String(m.title || m.name || `Journey ${idx + 1}`),
      description: String(m.description || m.objective || ""),
      objective: String(m.objective || m.description || ""),
      persona: m.persona ? String(m.persona) : undefined,
      steps: rawSteps.map((s) => (typeof s === "object" && s !== null ? (s as Record<string, unknown>) : String(s))),
      journey: Array.isArray(m.journey) ? m.journey.map(String) : undefined,
      // CRITICAL: keep the success condition structured. Stringifying it here
      // caused the verifier to receive {"description": "<json>"} — an unknown
      // condition — and treat the outcome as unprovable (or worse, vacuous).
      successCondition:
        typeof m.successCondition === "object" && m.successCondition !== null
          ? (m.successCondition as Record<string, unknown>)
          : null,
      recommended: Boolean(m.recommended),
    };
  });
}

export async function syncSessionState(
  sessionId: string,
  onEvent: (event: ExplorationEvent) => void,
  token?: string
) {
  try {
    let authToken = token;
    if (!authToken && typeof window !== "undefined") {
      authToken = (await getBrowserSessionToken()) ?? undefined;
    }
    const session = await getExplorationSession(sessionId, authToken);
    const normalizedState = normalizeExploreStatus(session.status);

    // Emit payload data BEFORE state change so state machine has data when transitioning
    if (session.credential_request && normalizedState === "auth_required") {
      onEvent({ type: "auth_required", request: session.credential_request });
    }
    if (session.question && normalizedState === "asking") {
      onEvent({ type: "question", question: session.question as AgentQuestionItem });
    }
    if (session.discoveries?.length > 0) {
      onEvent({ type: "discovery", discoveries: session.discoveries });
    }
    if (session.candidate_missions?.length > 0) {
      onEvent({
        type: "missions",
        missions: mapCandidateMissions(session.candidate_missions),
      });
    }
    if (session.error_message && normalizedState === "failed") {
      onEvent({ type: "error", message: session.error_message });
    }

    // Now transition to the new state
    onEvent({ type: "state_change", state: normalizedState });
  } catch {
    // Ignore sync errors
  }
}

// Current active exploration session ID tracker
let currentSessionId: string | null = null;

export function getCurrentSessionId(): string | null {
  return currentSessionId;
}

export async function startExploration(
  url: string,
  intent: string | undefined,
  onEvent: (event: ExplorationEvent) => void,
  signal?: AbortSignal,
  token?: string
): Promise<string> {
  onEvent({ type: "started", url });
  onEvent({ type: "state_change", state: "connecting" });

  try {
    const session = await createExplorationSession(url, intent, token);
    currentSessionId = session.id;

    // Safety net: periodically sync session state — runs independently of SSE
    let emptyReadyPollCount = 0;
    const pollInterval = setInterval(async () => {
      if (!currentSessionId) {
        clearInterval(pollInterval);
        return;
      }
      try {
        const latest = await getExplorationSession(currentSessionId, token);
        const normalizedState = normalizeExploreStatus(latest.status);

        // Emit data events for any missed state BEFORE state_change
        if (latest.credential_request && normalizedState === "auth_required") {
          onEvent({ type: "auth_required", request: latest.credential_request });
          if (latest.error_message) {
            onEvent({ type: "error", message: latest.error_message });
          }
        }
        if (latest.question && normalizedState === "asking") {
          onEvent({ type: "question", question: latest.question as AgentQuestionItem });
        }
        if (latest.discoveries && latest.discoveries.length > 0) {
          onEvent({ type: "discovery", discoveries: latest.discoveries });
        }
        if (latest.candidate_missions && latest.candidate_missions.length > 0) {
          onEvent({
            type: "missions",
            missions: mapCandidateMissions(latest.candidate_missions),
          });
        }
        if (latest.error_message && normalizedState === "failed") {
          onEvent({ type: "error", message: latest.error_message });
        }

        // If backend transitioned status to READY but candidate_missions are still committing,
        // wait up to 3 extra poll cycles before transitioning state to ready
        const missionsAvailable = (latest.candidate_missions?.length ?? 0) > 0;
        if (normalizedState === "ready" && !missionsAvailable && emptyReadyPollCount < 3) {
          emptyReadyPollCount++;
          return;
        }

        onEvent({ type: "state_change", state: normalizedState });

        // Stop polling on terminal states (only if ready has missions or poll count exceeded)
        if (
          ["completed", "failed", "cancelled"].includes(normalizedState) ||
          (normalizedState === "ready" && (missionsAvailable || emptyReadyPollCount >= 3))
        ) {
          clearInterval(pollInterval);
        }
      } catch {
        // Ignore poll errors
      }
    }, 3000);

    // Clean up poll on abort
    if (signal) {
      signal.addEventListener("abort", () => clearInterval(pollInterval));
    }

    // Stream live events — don't block polling; run in background
    streamExplorationEvents(session.id, onEvent, signal, token)
      .then(() => {
        // Stream ended — final sync
        syncSessionState(session.id, onEvent, token).then(() => {
          // Check terminal state after sync
          getExplorationSession(session.id, token).then((latest) => {
            const normalizedState = normalizeExploreStatus(latest.status);
            const missionsAvailable = (latest.candidate_missions?.length ?? 0) > 0;
            if (
              ["completed", "failed", "cancelled"].includes(normalizedState) ||
              (normalizedState === "ready" && missionsAvailable)
            ) {
              clearInterval(pollInterval);
            }
          }).catch(() => {});
        }).catch(() => {});
      })
      .catch(() => {});

    return session.id;
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to start exploration";
    onEvent({ type: "error", message });
    onEvent({ type: "state_change", state: "failed" });
    throw err;
  }
}

export async function submitCredential(
  email: string,
  password: string,
  onEvent: (event: ExplorationEvent) => void,
  signal?: AbortSignal,
  token?: string
): Promise<void> {
  if (!currentSessionId) {
    throw new Error("No active exploration session");
  }

  onEvent({ type: "state_change", state: "authenticating" });

  try {
    await submitExplorationCredentials(currentSessionId, email, password, false, token);
  } catch (err) {
    // If the POST itself fails (network, server), report it
    const message = err instanceof Error ? err.message : "Could not submit credentials to the server.";
    onEvent({ type: "error", message });
    onEvent({ type: "state_change", state: "auth_required" });
  }
}

export async function answerQuestion(
  questionId: string,
  answer: string,
  onEvent: (event: ExplorationEvent) => void,
  signal?: AbortSignal,
  token?: string
): Promise<void> {
  if (!currentSessionId) {
    throw new Error("No active exploration session");
  }

  onEvent({ type: "state_change", state: "discovering" });

  try {
    await submitExplorationAnswer(currentSessionId, questionId, answer, token);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to submit answer";
    onEvent({ type: "error", message });
    throw err;
  }
}

export async function cancelExploration(
  onEvent: (event: ExplorationEvent) => void,
  token?: string
): Promise<void> {
  if (currentSessionId) {
    try {
      await cancelExplorationSession(currentSessionId, token);
    } catch {
      // Best-effort cancel
    }
  }
  onEvent({ type: "state_change", state: "cancelled" });
}

export async function createAccount(
  email: string | undefined,
  password: string | undefined,
  onEvent: (event: ExplorationEvent) => void,
  signal?: AbortSignal,
  token?: string
): Promise<void> {
  if (!currentSessionId) {
    throw new Error("No active exploration session");
  }

  onEvent({ type: "state_change", state: "authenticating" });

  try {
    await createExplorationAccount(currentSessionId, email, password, token);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Could not create account on the server.";
    onEvent({ type: "error", message });
    onEvent({ type: "state_change", state: "auth_required" });
  }
}
