export type ExploreState =
  | "idle"
  | "connecting"
  | "loading"
  | "validating_page"
  | "exploring"
  | "understanding"
  | "auth_required"
  | "authenticating"
  | "asking"
  | "discovering"
  | "planning"
  | "ready"
  | "executing"
  | "completed"
  | "mission_selected"
  | "mission_created"
  | "failed"
  | "cancelled";

export interface Organization {
  id: string;
  name: string;
  slug: string;
  createdAt: string;
  updatedAt?: string;
}

export interface UserProfile {
  id: string;
  email: string;
  name: string;
  organizationId: string | null;
  organization: Organization | null;
}

export interface PendingIntent {
  url: string;
  instruction?: string;
  projectId?: string;
}

export interface AgentActivityItem {
  id: string;
  status: "pending" | "active" | "completed" | "failed";
  message: string;
}

export interface QuestionOption {
  id: string;
  label: string;
  description?: string;
  icon?: string;
}

export interface AgentQuestionItem {
  id: string;
  title: string;
  description?: string;
  type: "role" | "account" | "single_choice" | "confirmation";
  options: QuestionOption[];
}

export interface SuggestedMission {
  id: string;
  title: string;
  description: string;
  steps: Array<string | Record<string, unknown>>;
  journey?: string[];
  persona?: string;
  objective?: string;
  category?: string; // auth, feature, content, navigation
  /** Structured verification condition — must stay an object end-to-end. */
  successCondition?: Record<string, unknown> | null;
  recommended?: boolean;
  routeAnalysis?: {
    path: string;
    accessible: boolean;
    status: number;
    elementsCount: number;
  };
  estimatedTimeSeconds?: number;
}

export interface CredentialRequest {
  type: "login";
  reason: string;
  emailLabel?: string;
  passwordLabel?: string;
}

export interface ExplorationData {
  url: string;
  intent?: string;
  state: ExploreState;
  activities: AgentActivityItem[];
  discoveries: DiscoveryItem[];
  credentialRequest: CredentialRequest | null;
  question: AgentQuestionItem | null;
  missions: SuggestedMission[];
  error: string | null;
  projectName: string | null;
}

export interface DiscoveryItem {
  label: string;
  description: string;
}

export type ExplorationEvent =
  | { type: "started"; url: string }
  | { type: "progress"; activity: AgentActivityItem }
  | { type: "state_change"; state: ExploreState }
  | { type: "screenshot"; screenshot: string; url?: string; path?: string }
  | { type: "page_loaded"; url: string; title?: string; path?: string; screenshot?: string }
  | { type: "auth_required"; request: CredentialRequest }
  | { type: "question"; question: AgentQuestionItem }
  | { type: "discovery"; discoveries: DiscoveryItem[] }
  | { type: "missions"; missions: SuggestedMission[]; recommendation?: string }
  | { type: "completed"; projectName: string }
  | { type: "error"; message: string };

// ── Project ───────────────────────────────────────────────

export interface Project {
  id: string;
  userId: string;
  organizationId?: string;
  name: string;
  description: string | null;
  baseUrl: string;
  createdAt: string;
  updatedAt: string;
}

export interface ProjectSummary extends Project {
  missionCount?: number;
  executionCount?: number;
}

export interface ProjectActivity {
  id: string;
  type: "mission_completed" | "mission_failed" | "mission_created" | "execution_completed" | "execution_failed";
  title: string;
  description?: string;
  createdAt: string;
  executionId?: string;
  missionId?: string;
}

// ── Execution ──────────────────────────────────────────────

export type ExecutionStatus =
  | "created"
  | "queued"
  | "initializing"
  | "browser_ready"
  | "running"
  | "waiting"
  | "paused"
  | "human_controlled"
  | "resuming"
  | "completed"
  | "failed"
  | "cancelled"
  | "timeout"
  | "blocked"
  | "unverified";

export const executionStatusLabels: Record<ExecutionStatus, string> = {
  created: "Preparing execution",
  queued: "Waiting to start",
  initializing: "Preparing Kova",
  browser_ready: "Browser ready",
  running: "Kova is working",
  waiting: "Kova needs something",
  paused: "Kova paused",
  human_controlled: "You have control",
  resuming: "Resuming Kova",
  completed: "Completed",
  failed: "Execution failed",
  cancelled: "Execution cancelled",
  timeout: "Execution timed out",
  blocked: "Mission blocked (auth wall)",
  unverified: "Ran but couldn't verify",
};

export const executionStatusShortLabels: Record<ExecutionStatus, string> = {
  created: "Created",
  queued: "Queued",
  initializing: "Initializing",
  browser_ready: "Browser ready",
  running: "Running",
  waiting: "Waiting",
  paused: "Paused",
  human_controlled: "Your control",
  resuming: "Resuming",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  timeout: "Timed out",
  blocked: "Blocked",
  unverified: "Unverified",
};

export const terminalStatuses: ExecutionStatus[] = [
  "completed",
  "failed",
  "cancelled",
  "timeout",
  "blocked",
  "unverified",
];

export interface ExecutionDetail {
  id: string;
  missionId: string;
  missionName: string;
  projectName: string;
  projectUrl: string;
  status: ExecutionStatus;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  error: string | null;
}

export interface ExecutionEvent {
  id: string;
  executionId: string;
  eventType: string;
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface ActivityItem {
  id: string;
  label: string;
  status: "pending" | "active" | "completed" | "failed";
  timestamp?: string;
  icon?: string;
}

export interface ExecutionListParams {
  projectId?: string;
  missionId?: string;
  status?: ExecutionStatus;
  search?: string;
}

// ── Mission ────────────────────────────────────────────────

export interface Mission {
  id: string;
  projectId: string;
  projectName: string;
  projectUrl: string;
  name: string;
  description: string | null;
  persona: string | null;
  objective: string;
  steps: Array<{ action: string; selector?: string | null; value?: string | null; credential_id?: string | null; description?: string | null }>;
  /** Machine-verifiable success condition. Must stay structured — never stringified. */
  successCondition: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
}

export interface MissionExecution {
  id: string;
  missionId: string;
  status: ExecutionStatus;
  createdAt: string;
}

export interface CreateMissionInput {
  projectId: string;
  projectName: string;
  projectUrl: string;
  name: string;
  description?: string;
  persona?: string;
  objective: string;
  steps?: Array<string | Record<string, unknown>>;
  /** Structured verification condition — passed through verbatim to the backend. */
  successCondition?: Record<string, unknown>;
}

export interface UpdateMissionInput {
  name?: string;
  description?: string;
  persona?: string;
  objective?: string;
  steps?: Array<string | Record<string, unknown>>;
  /** Structured verification condition — passed through verbatim to the backend. */
  successCondition?: Record<string, unknown>;
}

// ── Credentials ──────────────────────────────────────────

export interface Credential {
  id: string;
  organizationId: string;
  projectId?: string | null;
  projectName?: string | null;
  name: string;
  email: string;
  role?: string | null;
  createdAt: string;
  updatedAt: string;
  lastUsedAt?: string | null;
}

export interface CreateCredentialInput {
  name: string;
  email: string;
  password: string;
  role?: string;
  projectId?: string;
}

export interface UpdateCredentialInput {
  name?: string;
  email?: string;
  password?: string;
  role?: string;
  projectId?: string;
}

export const credentialRoleOptions = [
  "Student",
  "Teacher",
  "Admin",
  "Manager",
  "User",
  "Other",
] as const;

export type CredentialRole = (typeof credentialRoleOptions)[number];

// ── Organization / Team ───────────────────────────────────

export type MemberRole = "owner" | "member";

export const memberRoleLabels: Record<MemberRole, string> = {
  owner: "Owner",
  member: "Member",
};

export interface OrganizationMember {
  id: string;
  organizationId: string;
  userId: string;
  name: string;
  email: string;
  role: MemberRole;
  isCurrentUser: boolean;
  createdAt: string;
}

export interface OrganizationInvitation {
  id: string;
  email: string;
  role: MemberRole;
  status: "pending" | "accepted" | "expired";
  createdAt: string;
  expiresAt: string | null;
}

export interface UpdateOrganizationInput {
  name?: string;
}

export interface InviteMemberInput {
  email: string;
  role: MemberRole;
}

export interface UpdateMemberRoleInput {
  memberId: string;
  role: MemberRole;
}
