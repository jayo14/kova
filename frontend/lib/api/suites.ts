import { api } from "./client";

export type SuiteMode = "full" | "targeted" | "prioritized";

export interface SuiteVersion {
  id: string;
  suiteId: string;
  version: number;
  flowSnapshot: Array<Record<string, unknown>>;
  checksum: string;
  notes?: string | null;
  createdAt: string;
}

export interface SuiteSummary {
  id: string;
  projectId: string;
  name: string;
  description?: string | null;
  active: boolean;
  currentVersion: number;
  createdAt: string;
  updatedAt: string;
}

export interface SuiteRunSummary {
  total: number;
  executed: number;
  passed: number;
  failed: number;
  blocked: number;
  unverified: number;
  skipped: number;
  error: number;
  newFailures: number;
  persistentFailures: number;
  recoveredFailures: number;
  newCoverage: number;
  removedCoverage: number;
  changedTests: number;
  inconclusive: number;
  flaky: number;
  coverageComplete: boolean;
  verdict: string;
  regressed: boolean;
}

export interface SuiteRunItem {
  id: string;
  flowId?: string | null;
  flowName: string;
  position: number;
  status: string;
  durationMs: number;
  executionId?: string | null;
  assertions: Array<Record<string, unknown>>;
  failureSignature?: string | null;
  classification?: string | null;
  unstable: boolean;
  rationale?: string | null;
}

export interface SuiteRun {
  id: string;
  suiteId: string;
  projectId: string;
  suiteVersion: number;
  mode: string;
  status: string;
  baselineRunId?: string | null;
  baselineReason?: string | null;
  comparison: Record<string, unknown>;
  changedFiles: string[];
  commitSha?: string | null;
  branch?: string | null;
  summary: SuiteRunSummary;
  errorMessage?: string | null;
  startedAt?: string | null;
  completedAt?: string | null;
  createdAt: string;
  items?: SuiteRunItem[];
}

export interface SuiteDetail extends SuiteSummary {
  version: SuiteVersion;
  lastRun?: SuiteRun | null;
}

export interface FlakyFlow {
  flowId: string;
  flowName: string;
  transitions: number;
  runsConsidered: number;
  statuses: string[];
  flaky: boolean;
}

interface BackendSuite {
  id: string;
  project_id: string;
  name: string;
  description?: string | null;
  active: boolean;
  current_version: number;
  created_at: string;
  updated_at: string;
}

interface BackendSuiteVersion {
  id: string;
  suite_id: string;
  version: number;
  flow_snapshot: Array<Record<string, unknown>>;
  checksum: string;
  notes?: string | null;
  created_at: string;
}

interface BackendSuiteRun {
  id: string;
  suite_id: string;
  project_id: string;
  suite_version: number;
  mode: string;
  status: string;
  baseline_run_id?: string | null;
  baseline_reason?: string | null;
  comparison: Record<string, unknown>;
  changed_files: string[];
  commit_sha?: string | null;
  branch?: string | null;
  summary: Record<string, unknown>;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  items?: BackendSuiteRunItem[];
}

interface BackendSuiteRunItem {
  id: string;
  flow_id?: string | null;
  flow_name: string;
  position: number;
  status: string;
  duration_ms: number;
  execution_id?: string | null;
  assertions: Array<Record<string, unknown>>;
  failure_signature?: string | null;
  classification?: string | null;
  unstable: boolean;
  rationale?: string | null;
}

function mapSuite(row: BackendSuite): SuiteSummary {
  return {
    id: row.id,
    projectId: row.project_id,
    name: row.name,
    description: row.description,
    active: row.active,
    currentVersion: row.current_version,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

function mapRunSummary(raw: Record<string, unknown>): SuiteRunSummary {
  const number = (key: string) => Number(raw[key] ?? 0);
  return {
    total: number("total"),
    executed: number("executed"),
    passed: number("passed"),
    failed: number("failed"),
    blocked: number("blocked"),
    unverified: number("unverified"),
    skipped: number("skipped"),
    error: number("error"),
    newFailures: number("new_failures"),
    persistentFailures: number("persistent_failures"),
    recoveredFailures: number("recovered_failures"),
    newCoverage: number("new_coverage"),
    removedCoverage: number("removed_coverage"),
    changedTests: number("changed_tests"),
    inconclusive: number("inconclusive"),
    flaky: number("flaky"),
    coverageComplete: Boolean(raw.coverage_complete),
    verdict: String(raw.verdict ?? "unknown"),
    regressed: Boolean(raw.regressed),
  };
}

function mapRun(row: BackendSuiteRun): SuiteRun {
  return {
    id: row.id,
    suiteId: row.suite_id,
    projectId: row.project_id,
    suiteVersion: row.suite_version,
    mode: row.mode,
    status: row.status,
    baselineRunId: row.baseline_run_id,
    baselineReason: row.baseline_reason,
    comparison: row.comparison ?? {},
    changedFiles: row.changed_files ?? [],
    commitSha: row.commit_sha,
    branch: row.branch,
    summary: mapRunSummary(row.summary ?? {}),
    errorMessage: row.error_message,
    startedAt: row.started_at,
    completedAt: row.completed_at,
    createdAt: row.created_at,
    items: row.items?.map((item) => ({
      id: item.id,
      flowId: item.flow_id,
      flowName: item.flow_name,
      position: item.position,
      status: item.status,
      durationMs: item.duration_ms,
      executionId: item.execution_id,
      assertions: item.assertions ?? [],
      failureSignature: item.failure_signature,
      classification: item.classification,
      unstable: item.unstable,
      rationale: item.rationale,
    })),
  };
}

export async function listSuites(
  projectId: string,
  token?: string
): Promise<SuiteSummary[]> {
  const rows = await api.get<BackendSuite[]>(
    `/api/v1/suites/?project_id=${encodeURIComponent(projectId)}`,
    token
  );
  return rows.map(mapSuite);
}

export async function getSuite(
  suiteId: string,
  token?: string
): Promise<SuiteDetail> {
  const row = await api.get<BackendSuite & { version: BackendSuiteVersion; last_run?: BackendSuiteRun | null }>(
    `/api/v1/suites/${encodeURIComponent(suiteId)}`,
    token
  );
  return {
    ...mapSuite(row),
    version: {
      id: row.version.id,
      suiteId: row.version.suite_id,
      version: row.version.version,
      flowSnapshot: row.version.flow_snapshot ?? [],
      checksum: row.version.checksum,
      notes: row.version.notes,
      createdAt: row.version.created_at,
    },
    lastRun: row.last_run ? mapRun(row.last_run) : null,
  };
}

export async function createSuite(
  payload: { projectId: string; name: string; description?: string; flowIds: string[] },
  token?: string
): Promise<SuiteSummary> {
  const row = await api.post<BackendSuite>(
    "/api/v1/suites/",
    {
      project_id: payload.projectId,
      name: payload.name,
      description: payload.description,
      flow_ids: payload.flowIds,
    },
    token
  );
  return mapSuite(row);
}

export async function updateSuite(
  suiteId: string,
  payload: { name?: string; description?: string; active?: boolean; flowIds?: string[]; notes?: string },
  token?: string
): Promise<SuiteSummary> {
  const row = await api.patch<BackendSuite>(
    `/api/v1/suites/${encodeURIComponent(suiteId)}`,
    {
      name: payload.name,
      description: payload.description,
      active: payload.active,
      flow_ids: payload.flowIds,
      notes: payload.notes,
    },
    token
  );
  return mapSuite(row);
}

export async function runSuite(
  suiteId: string,
  payload: { mode: SuiteMode; baselineRunId?: string; changedFiles?: string[]; commitSha?: string; branch?: string },
  token?: string
): Promise<SuiteRun> {
  const row = await api.post<BackendSuiteRun>(
    `/api/v1/suites/${encodeURIComponent(suiteId)}/runs`,
    {
      mode: payload.mode,
      baseline_run_id: payload.baselineRunId,
      changed_files: payload.changedFiles ?? [],
      commit_sha: payload.commitSha,
      branch: payload.branch,
    },
    { token, timeoutMs: 300000 }
  );
  return mapRun(row);
}

export async function listSuiteRuns(
  suiteId: string,
  token?: string
): Promise<SuiteRun[]> {
  const rows = await api.get<BackendSuiteRun[]>(
    `/api/v1/suites/${encodeURIComponent(suiteId)}/runs`,
    token
  );
  return rows.map(mapRun);
}

export async function getSuiteRun(
  runId: string,
  token?: string
): Promise<SuiteRun> {
  const row = await api.get<BackendSuiteRun>(
    `/api/v1/suite-runs/${encodeURIComponent(runId)}`,
    token
  );
  return mapRun(row);
}

export async function getSuiteFlakiness(
  suiteId: string,
  token?: string
): Promise<FlakyFlow[]> {
  const data = await api.get<{
    suite_id: string;
    flows: Array<{
      flow_id: string;
      flow_name: string;
      transitions: number;
      runs_considered: number;
      statuses: string[];
      flaky: boolean;
    }>;
  }>(`/api/v1/suites/${encodeURIComponent(suiteId)}/flakiness`, token);
  return data.flows.map((flow) => ({
    flowId: flow.flow_id,
    flowName: flow.flow_name,
    transitions: flow.transitions,
    runsConsidered: flow.runs_considered,
    statuses: flow.statuses,
    flaky: flow.flaky,
  }));
}
