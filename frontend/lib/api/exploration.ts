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
  Credential,
} from "@/lib/types";
import { api, getApiBaseUrl, getBrowserSessionToken } from "./client";
import { getErrorMessage } from "./errors";
import { backendToCredential, type BackendCredential } from "./credentials";
import type { BackendFlow } from "./missions";

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
    case "blocked":
      return "blocked";
    case "cancelled":
      return "cancelled";
    default:
      return "connecting";
  }
}

export function normalizeTargetUrl(rawUrl: string): string {
  const trimmed = rawUrl.trim();
  if (!trimmed) return trimmed;
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (/^(?:localhost|127\.0\.0\.1)(?::\d+)?(?:\/.*)?$/i.test(trimmed)) {
    return `http://${trimmed}`;
  }
  return `https://${trimmed}`;
}

export async function createExplorationSession(
  url: string,
  goal?: string,
  token?: string
): Promise<BackendExplorationSession> {
  const cleanUrl = normalizeTargetUrl(url);
  return await api.post<BackendExplorationSession>(
    "/api/v1/exploration/",
    { url: cleanUrl, goal },
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

export interface SubmitExplorationCredentialsOptions {
  email?: string;
  password?: string;
  credentialId?: string;
  save?: boolean;
}

export async function submitExplorationCredentials(
  sessionId: string,
  emailOrOptions?: string | SubmitExplorationCredentialsOptions,
  password?: string,
  save = false,
  token?: string
): Promise<BackendExplorationSession> {
  const body: Record<string, unknown> = { save };
  if (typeof emailOrOptions === "object" && emailOrOptions !== null) {
    if (emailOrOptions.email) body.email = emailOrOptions.email;
    if (emailOrOptions.password) body.password = emailOrOptions.password;
    if (emailOrOptions.credentialId) body.credential_id = emailOrOptions.credentialId;
    if (emailOrOptions.save !== undefined) body.save = emailOrOptions.save;
  } else {
    if (emailOrOptions) body.email = emailOrOptions;
    if (password) body.password = password;
  }
  return await api.post<BackendExplorationSession>(
    `/api/v1/exploration/${encodeURIComponent(sessionId)}/credentials`,
    body,
    token
  );
}

export async function getExplorationCredentials(
  sessionId: string,
  token?: string
): Promise<Credential[]> {
  try {
    const raw = await api.get<BackendCredential[]>(
      `/api/v1/exploration/${encodeURIComponent(sessionId)}/credentials`,
      token
    );
    return raw.map((c) => backendToCredential(c));
  } catch {
    return [];
  }
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
 * Promote an exploration candidate mission into a project Flow.
 */
export async function promoteMission(
  sessionId: string,
  missionId: string,
  options?: {
    projectId?: string;
    activateImmediately?: boolean;
    name?: string;
  },
  token?: string
): Promise<BackendFlow> {
  return await api.post<BackendFlow>(
    `/api/v1/exploration/${encodeURIComponent(sessionId)}/missions/${encodeURIComponent(missionId)}/promote`,
    {
      project_id: options?.projectId,
      activate_immediately: options?.activateImmediately ?? false,
      name: options?.name,
    },
    token
  );
}

let activeStreamSessionId: string | null = null;

/**
 * Connects to live Server-Sent Events stream for an exploration session.
 */
export async function streamExplorationEvents(
  sessionId: string,
  onEvent: (event: ExplorationEvent) => void,
  signal?: AbortSignal,
  token?: string
): Promise<void> {
  setCurrentSessionId(sessionId);
  if (activeStreamSessionId === sessionId) {
    return;
  }
  activeStreamSessionId = sessionId;

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
  } finally {
    if (activeStreamSessionId === sessionId) {
      activeStreamSessionId = null;
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
  } else if (type === "exploration.blocked" || type === "blocked") {
    const reasonMsg =
      typeof inner.reason === "string"
        ? inner.reason
        : typeof raw.reason === "string"
        ? raw.reason
        : "Target application did not become ready";
    onEvent({
      type: "error",
      message: reasonMsg,
    });
    onEvent({
      type: "state_change",
      state: "blocked",
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
      personaEvidence: m.persona_evidence ? String(m.persona_evidence) : undefined,
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
      expectationSource: m.expectation_source === "observed" || m.expectation_source === "inferred" ? m.expectation_source : "unspecified",
      reviewRequired: m.review_required !== false,
      discoveryEvidence: Array.isArray(m.discovery_evidence) ? m.discovery_evidence as Array<Record<string, unknown>> : [],
      flowId: m.flow_id ? String(m.flow_id) : undefined,
      promoted: Boolean(m.promoted),
    };
  });
}

export async function syncSessionState(
  sessionId: string,
  onEvent: (event: ExplorationEvent) => void,
  token?: string
) {
  try {
    setCurrentSessionId(sessionId);
    let authToken = token;
    if (!authToken && typeof window !== "undefined") {
      authToken = (await getBrowserSessionToken()) ?? undefined;
    }
    const session = await getExplorationSession(sessionId, authToken);
    if (session.project_id) {
      setCurrentProjectId(session.project_id);
    }
    const normalizedState = normalizeExploreStatus(session.status);

    // Emit payload data BEFORE state change so state machine has data when transitioning
    if (session.credential_request && normalizedState === "auth_required") {
      const authReq = {
        ...session.credential_request,
        ...(session.project_id && { projectId: session.project_id, project_id: session.project_id }),
      };
      onEvent({ type: "auth_required", request: authReq as CredentialRequest });
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
    if (session.error_message && (normalizedState === "failed" || normalizedState === "blocked")) {
      onEvent({ type: "error", message: session.error_message });
    }

    // Now transition to the new state
    onEvent({ type: "state_change", state: normalizedState });
  } catch {
    // Ignore sync errors
  }
}

// Current active exploration session and project ID trackers
let currentSessionId: string | null = null;
let currentProjectId: string | null = null;

export function getCurrentSessionId(): string | null {
  if (currentSessionId) return currentSessionId;
  if (typeof window !== "undefined") {
    try {
      const stored = window.sessionStorage.getItem("kova_active_exploration_session");
      if (stored) {
        currentSessionId = stored;
        return stored;
      }
    } catch {}
  }
  return null;
}

export function setCurrentSessionId(id: string | null): void {
  currentSessionId = id;
  if (typeof window !== "undefined") {
    try {
      if (id) {
        window.sessionStorage.setItem("kova_active_exploration_session", id);
      } else {
        window.sessionStorage.removeItem("kova_active_exploration_session");
      }
    } catch {}
  }
}

export function getCurrentProjectId(): string | null {
  if (currentProjectId) return currentProjectId;
  if (typeof window !== "undefined") {
    try {
      const stored = window.sessionStorage.getItem("kova_active_exploration_project");
      if (stored) {
        currentProjectId = stored;
        return stored;
      }
    } catch {}
  }
  return null;
}

export function setCurrentProjectId(id: string | null): void {
  currentProjectId = id;
  if (typeof window !== "undefined") {
    try {
      if (id) {
        window.sessionStorage.setItem("kova_active_exploration_project", id);
      } else {
        window.sessionStorage.removeItem("kova_active_exploration_project");
      }
    } catch {}
  }
}

export async function startExploration(
  url: string,
  intent: string | undefined,
  onEvent: (event: ExplorationEvent) => void,
  signal?: AbortSignal,
  token?: string
): Promise<string> {
  const cleanUrl = normalizeTargetUrl(url);
  onEvent({ type: "started", url: cleanUrl });
  onEvent({ type: "state_change", state: "connecting" });

  try {
    const session = await createExplorationSession(cleanUrl, intent, token);
    setCurrentSessionId(session.id);
    if (session.project_id) {
      setCurrentProjectId(session.project_id);
    }

    // Safety net: periodically sync session state — runs independently of SSE
    let emptyReadyPollCount = 0;
    const pollInterval = setInterval(async () => {
      const targetId = getCurrentSessionId();
      if (!targetId) {
        clearInterval(pollInterval);
        return;
      }
      try {
        const latest = await getExplorationSession(targetId, token);
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
      } catch (err: any) {
        // Stop polling if session is not found (404) or on fatal abort
        if (err?.status === 404 || (err?.message && String(err.message).includes("404"))) {
          clearInterval(pollInterval);
        }
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
    const message = getErrorMessage(err, "Failed to start exploration");
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
  token?: string,
  sessionId?: string | null
): Promise<void> {
  const targetSessionId = sessionId || getCurrentSessionId();
  if (!targetSessionId) {
    throw new Error("No active exploration session");
  }
  setCurrentSessionId(targetSessionId);

  onEvent({ type: "state_change", state: "authenticating" });

  try {
    const updated = await submitExplorationCredentials(targetSessionId, email, password, false, token);
    if (updated?.status) {
      onEvent({ type: "state_change", state: normalizeExploreStatus(updated.status) });
    }
    if (activeStreamSessionId !== targetSessionId) {
      streamExplorationEvents(targetSessionId, onEvent, signal, token).catch(() => {});
    }
  } catch (err) {
    // If the POST itself fails (network, server), report it
    const message = err instanceof Error ? err.message : "Could not submit credentials to the server.";
    onEvent({ type: "error", message });
    onEvent({ type: "state_change", state: "auth_required" });
  }
}

export async function submitExistingCredential(
  credentialId: string,
  onEvent: (event: ExplorationEvent) => void,
  signal?: AbortSignal,
  token?: string,
  sessionId?: string | null
): Promise<void> {
  const targetSessionId = sessionId || getCurrentSessionId();
  if (!targetSessionId) {
    throw new Error("No active exploration session");
  }
  setCurrentSessionId(targetSessionId);

  onEvent({ type: "state_change", state: "authenticating" });

  try {
    const updated = await submitExplorationCredentials(
      targetSessionId,
      { credentialId },
      undefined,
      false,
      token
    );
    if (updated?.status) {
      onEvent({ type: "state_change", state: normalizeExploreStatus(updated.status) });
    }
    if (activeStreamSessionId !== targetSessionId) {
      streamExplorationEvents(targetSessionId, onEvent, signal, token).catch(() => {});
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Could not sign in with stored credential.";
    onEvent({ type: "error", message });
    onEvent({ type: "state_change", state: "auth_required" });
    throw err;
  }
}

export async function answerQuestion(
  questionId: string,
  answer: string,
  onEvent: (event: ExplorationEvent) => void,
  signal?: AbortSignal,
  token?: string,
  sessionId?: string | null
): Promise<void> {
  const targetSessionId = sessionId || getCurrentSessionId();
  if (!targetSessionId) {
    throw new Error("No active exploration session");
  }
  setCurrentSessionId(targetSessionId);

  onEvent({ type: "state_change", state: "discovering" });

  try {
    await submitExplorationAnswer(targetSessionId, questionId, answer, token);
    if (activeStreamSessionId !== targetSessionId) {
      streamExplorationEvents(targetSessionId, onEvent, signal, token).catch(() => {});
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to submit answer";
    onEvent({ type: "error", message });
    throw err;
  }
}

export async function cancelExploration(
  onEvent?: (event: ExplorationEvent) => void,
  token?: string,
  sessionId?: string | null
): Promise<void> {
  const targetSessionId = sessionId || getCurrentSessionId();
  if (targetSessionId) {
    try {
      await cancelExplorationSession(targetSessionId, token);
    } catch {
      // Best-effort cancel
    }
    if (currentSessionId === targetSessionId) {
      setCurrentSessionId(null);
    }
  }
  if (onEvent) {
    onEvent({ type: "state_change", state: "cancelled" });
  }
}

export async function createAccount(
  email: string | undefined,
  password: string | undefined,
  onEvent: (event: ExplorationEvent) => void,
  signal?: AbortSignal,
  token?: string,
  sessionId?: string | null
): Promise<void> {
  const targetSessionId = sessionId || getCurrentSessionId();
  if (!targetSessionId) {
    throw new Error("No active exploration session");
  }
  setCurrentSessionId(targetSessionId);

  onEvent({ type: "state_change", state: "authenticating" });

  try {
    const updated = await createExplorationAccount(targetSessionId, email, password, token);
    if (updated?.status) {
      onEvent({ type: "state_change", state: normalizeExploreStatus(updated.status) });
    }
    if (activeStreamSessionId !== targetSessionId) {
      streamExplorationEvents(targetSessionId, onEvent, signal, token).catch(() => {});
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Could not create account on the server.";
    onEvent({ type: "error", message });
    onEvent({ type: "state_change", state: "auth_required" });
  }
}
