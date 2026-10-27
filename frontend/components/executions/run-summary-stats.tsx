import type { RunSummary } from "@/lib/api/runs";
import { normalizeRunStatus } from "@/lib/executions/run-status";
import { cn } from "@/lib/utils";

interface RunSummaryStatsProps {
  summary: RunSummary;
  progress: number;
  status: string;
}

interface Segment {
  key: string;
  label: string;
  count: number;
  barClass: string;
  dotClass: string;
}

export function RunSummaryStats({
  summary,
  progress,
  status,
}: RunSummaryStatsProps) {
  const runStatus = normalizeRunStatus(status);
  const isTerminalRun = runStatus === "PASSED" || runStatus === "FAILED";
  const completed = summary.passed + summary.failed + summary.blocked + (summary.unverified || 0);

  const segments: Segment[] = [
    { key: "passed", label: "Passed", count: summary.passed, barClass: "bg-emerald-500", dotClass: "bg-emerald-500" },
    { key: "failed", label: "Failed", count: summary.failed, barClass: "bg-destructive", dotClass: "bg-destructive" },
    { key: "running", label: "Running", count: summary.running, barClass: "bg-blue-500", dotClass: "bg-blue-500" },
    { key: "blocked", label: "Blocked", count: summary.blocked, barClass: "bg-amber-500", dotClass: "bg-amber-500" },
    { key: "unverified", label: "Unverified", count: summary.unverified || 0, barClass: "bg-purple-500", dotClass: "bg-purple-500" },
    { key: "queued", label: "Queued", count: summary.queued, barClass: "bg-[var(--sand)]", dotClass: "bg-[var(--sand)]" },
  ];

  const active = segments.filter((s) => s.count > 0);

  return (
    <section className="rounded-[20px] border border-border/70 bg-card p-5 shadow-[0_1px_2px_rgba(42,23,13,0.04)]">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">
          Overall Progress <span className="text-muted-foreground">({progress}%)</span>
        </h2>
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {completed}/{summary.total}
        </span>
      </div>

      {/* Segmented outcome bar — one glance at what happened to each mission */}
      <div
        role="progressbar"
        aria-valuenow={progress}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Overall run progress"
        className="mt-3 flex h-2.5 w-full overflow-hidden rounded-full bg-[var(--sand)]"
      >
        {active.map((segment) => (
          <span
            key={segment.key}
            title={`${segment.label}: ${segment.count}`}
            style={{
              width: `${(segment.count / Math.max(summary.total, 1)) * 100}%`,
              minWidth: "4px",
            }}
            className={cn(
              "h-full",
              segment.barClass,
              segment.key === "running" && !isTerminalRun && "animate-pulse"
            )}
          />
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p className="text-xs text-muted-foreground">
          {completed} of {summary.total} {summary.total === 1 ? "mission" : "missions"} completed
        </p>
        <ul className="flex flex-wrap items-center gap-1.5">
          {active.length === 0 && (
            <li className="text-xs text-muted-foreground">No missions in this run yet</li>
          )}
          {active.map((segment) => (
            <li
              key={segment.key}
              className="inline-flex items-center gap-1.5 rounded-full bg-secondary/70 px-2 py-0.5 text-[11px] text-muted-foreground"
              aria-label={`${segment.label}: ${segment.count}`}
            >
              <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", segment.dotClass)} />
              <span className="font-medium text-foreground/90">{segment.count}</span>
              <span>{segment.label}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
