"use client";

import { useCallback, useEffect, useState } from "react";
import type { Mission } from "@/lib/types";
import { MaterialIcon } from "@/components/shared/material-icon";
import {
  createSuite,
  getSuiteFlakiness,
  getSuiteRun,
  listSuiteRuns,
  listSuites,
  runSuite,
  type FlakyFlow,
  type SuiteMode,
  type SuiteRun,
  type SuiteSummary,
} from "@/lib/api/suites";
import { getErrorMessage } from "@/lib/api/errors";

interface ProjectSuitesProps {
  projectId: string;
  missions: Mission[];
}

const verdictTone: Record<string, string> = {
  regression: "bg-destructive/10 text-destructive",
  improved: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  unchanged: "bg-secondary text-secondary-foreground",
  inconclusive: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
};

const classificationTone: Record<string, string> = {
  new_failure: "text-destructive",
  persistent_failure: "text-destructive",
  recovered_failure: "text-emerald-600",
  changed_test: "text-amber-600",
  inconclusive: "text-amber-600",
  new_coverage: "text-primary",
  removed_coverage: "text-muted-foreground",
  stable: "text-muted-foreground",
};

export function ProjectSuites({ projectId, missions }: ProjectSuitesProps) {
  const [suites, setSuites] = useState<SuiteSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [runs, setRuns] = useState<SuiteRun[]>([]);
  const [openRunId, setOpenRunId] = useState<string | null>(null);
  const [runDetails, setRunDetails] = useState<Record<string, SuiteRun>>({});
  const [flakiness, setFlakiness] = useState<FlakyFlow[]>([]);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [flowIds, setFlowIds] = useState<string[]>([]);
  const [changedFiles, setChangedFiles] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSuites = useCallback(async () => {
    try {
      const rows = await listSuites(projectId);
      setSuites(rows);
      setSelectedId((current) => current ?? rows[0]?.id ?? null);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  }, [projectId]);

  useEffect(() => {
    async function load() {
      await loadSuites();
    }
    load();
  }, [loadSuites]);

  const loadDetail = useCallback(async (suiteId: string) => {
    try {
      const [history, flaky] = await Promise.all([
        listSuiteRuns(suiteId),
        getSuiteFlakiness(suiteId),
      ]);
      setRuns(history);
      setFlakiness(flaky);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    async function load() {
      setOpenRunId(null);
      setRunDetails({});
      await loadDetail(selectedId as string);
    }
    load();
  }, [selectedId, loadDetail]);

  const visibleRuns = selectedId ? runs : [];
  const visibleFlakiness = selectedId ? flakiness : [];

  async function handleCreate() {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const suite = await createSuite({
        projectId,
        name: name.trim(),
        flowIds,
      });
      setName("");
      setFlowIds([]);
      setCreating(false);
      await loadSuites();
      setSelectedId(suite.id);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleRun(mode: SuiteMode) {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    try {
      const files = changedFiles
        .split(/[\n,]/)
        .map((file) => file.trim())
        .filter(Boolean);
      const run = await runSuite(selectedId, { mode, changedFiles: files });
      setRunDetails((current) => ({ ...current, [run.id]: run }));
      setOpenRunId(run.id);
      await loadDetail(selectedId);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function toggleRun(run: SuiteRun) {
    if (openRunId === run.id) {
      setOpenRunId(null);
      return;
    }
    setOpenRunId(run.id);
    if (runDetails[run.id]) return;
    try {
      const detail = await getSuiteRun(run.id);
      setRunDetails((current) => ({ ...current, [run.id]: detail }));
    } catch (err) {
      setError(getErrorMessage(err));
    }
  }

  function toggleFlow(flowId: string) {
    setFlowIds((current) =>
      current.includes(flowId)
        ? current.filter((id) => id !== flowId)
        : [...current, flowId]
    );
  }

  const selected = suites.find((suite) => suite.id === selectedId) ?? null;
  const flakyFlows = visibleFlakiness.filter((flow) => flow.flaky);

  return (
    <div className="rounded-xl border border-border bg-card/40 p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <MaterialIcon name="layers" size={20} className="text-primary" />
          <h3 className="text-body font-semibold text-foreground">Test Suites</h3>
        </div>
        <button
          type="button"
          onClick={() => setCreating((value) => !value)}
          className="text-caption font-medium text-primary hover:underline inline-flex items-center gap-1"
        >
          <MaterialIcon name={creating ? "close" : "add"} size={14} />
          {creating ? "Cancel" : "New suite"}
        </button>
      </div>

      {error && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-caption text-destructive">
          {error}
        </p>
      )}

      {creating && (
        <div className="rounded-lg border border-border bg-background/70 p-4 space-y-3">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Suite name (e.g. Checkout smoke)"
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-body-sm outline-none focus:border-primary"
          />
          <div className="max-h-40 space-y-1 overflow-y-auto">
            {missions.length === 0 ? (
              <p className="text-caption text-muted-foreground">No flows available.</p>
            ) : (
              missions.map((mission) => (
                <label
                  key={mission.id}
                  className="flex items-center gap-2 text-body-sm text-foreground"
                >
                  <input
                    type="checkbox"
                    checked={flowIds.includes(mission.id)}
                    onChange={() => toggleFlow(mission.id)}
                  />
                  {mission.name}
                </label>
              ))
            )}
          </div>
          <button
            type="button"
            disabled={busy || !name.trim()}
            onClick={handleCreate}
            className="rounded-md bg-primary px-3 py-2 text-body-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            Create suite
          </button>
        </div>
      )}

      {suites.length === 0 ? (
        <p className="text-body-sm text-muted-foreground py-2">
          No suites yet. Group flows into a suite to get repeatable runs, baseline
          regression diffs, and flakiness detection.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {suites.map((suite) => (
              <button
                key={suite.id}
                type="button"
                onClick={() => setSelectedId(suite.id)}
                className={`rounded-full border px-3 py-1 text-caption font-medium transition-colors ${
                  suite.id === selectedId
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:text-foreground"
                }`}
              >
                {suite.name}
                <span className="ml-1 font-mono opacity-60">v{suite.currentVersion}</span>
              </button>
            ))}
          </div>

          {selected && (
            <div className="space-y-3 border-t border-border/60 pt-3">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={changedFiles}
                  onChange={(event) => setChangedFiles(event.target.value)}
                  placeholder="Changed files (comma or newline separated)"
                  className="min-w-[220px] flex-1 rounded-md border border-border bg-background px-3 py-2 text-caption outline-none focus:border-primary"
                />
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => handleRun("full")}
                  className="rounded-md border border-border px-3 py-2 text-caption font-medium text-foreground disabled:opacity-50"
                >
                  Run full
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => handleRun("targeted")}
                  className="rounded-md border border-border px-3 py-2 text-caption font-medium text-foreground disabled:opacity-50"
                >
                  Run changed
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => handleRun("prioritized")}
                  className="rounded-md bg-primary px-3 py-2 text-caption font-medium text-primary-foreground disabled:opacity-50"
                >
                  Run prioritized
                </button>
              </div>

              {flakyFlows.length > 0 && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-caption text-amber-700 dark:text-amber-400">
                  Flaky: {flakyFlows.map((flow) => flow.flowName).join(", ")}
                </div>
              )}

              {visibleRuns.length === 0 ? (
                <p className="text-caption text-muted-foreground">
                  No runs yet for this suite.
                </p>
              ) : (
                <div className="space-y-2">
                  {visibleRuns.map((run) => {
                    const open = openRunId === run.id;
                    const detail = runDetails[run.id];
                    return (
                      <div
                        key={run.id}
                        className="rounded-lg border border-border/80 bg-background/50"
                      >
                        <button
                          type="button"
                          onClick={() => toggleRun(run)}
                          className="flex w-full flex-wrap items-center justify-between gap-2 px-3 py-2 text-left"
                        >
                          <span className="flex items-center gap-2 text-caption">
                            <span className="font-mono text-muted-foreground">
                              {new Date(run.createdAt).toLocaleString()}
                            </span>
                            <span className="rounded bg-secondary px-1.5 py-0.5 font-mono uppercase text-secondary-foreground">
                              {run.mode}
                            </span>
                            <span className="text-muted-foreground">
                              v{run.suiteVersion}
                            </span>
                          </span>
                          <span className="flex items-center gap-2 text-caption">
                            <span className="text-muted-foreground">
                              {run.summary.passed} passed · {run.summary.failed} failed
                            </span>
                            <span
                              className={`rounded px-2 py-0.5 font-semibold ${
                                verdictTone[run.summary.verdict] ??
                                "bg-secondary text-muted-foreground"
                              }`}
                            >
                              {run.summary.verdict}
                            </span>
                          </span>
                        </button>

                        {open && (
                          <div className="space-y-2 border-t border-border/60 px-3 py-2">
                            {(detail?.baselineReason ?? run.baselineReason) && (
                              <p className="text-caption text-muted-foreground">
                                Baseline: {detail?.baselineReason ?? run.baselineReason}
                              </p>
                            )}
                            {!detail && (
                              <p className="text-caption text-muted-foreground">Loading run detail…</p>
                            )}
                            {(detail?.items ?? []).map((item) => (
                              <div
                                key={item.id}
                                className="flex flex-wrap items-center justify-between gap-2 text-caption"
                              >
                                <span className="flex items-center gap-2">
                                  <span className="font-mono text-muted-foreground">
                                    {item.position + 1}.
                                  </span>
                                  <span className="text-foreground">{item.flowName}</span>
                                  <span className="text-muted-foreground">{item.status}</span>
                                  {item.unstable && (
                                    <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-amber-700 dark:text-amber-400">
                                      flaky
                                    </span>
                                  )}
                                </span>
                                <span className="flex items-center gap-2">
                                  {item.classification && (
                                    <span
                                      className={
                                        classificationTone[item.classification] ??
                                        "text-muted-foreground"
                                      }
                                    >
                                      {item.classification.replaceAll("_", " ")}
                                    </span>
                                  )}
                                  <span className="font-mono text-muted-foreground">
                                    {item.durationMs}ms
                                  </span>
                                </span>
                              </div>
                            ))}
                            {(detail?.summary ?? run.summary).newFailures > 0 && (
                              <p className="text-caption text-destructive">
                                {(detail?.summary ?? run.summary).newFailures} new failure(s) ·{" "}
                                {(detail?.summary ?? run.summary).persistentFailures} persistent
                              </p>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
