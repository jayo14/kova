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
    <div className="space-y-2.5 pt-2 border-t border-border/40">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs text-muted-foreground font-medium">
        <span>
          Overall Progress ({progress}%)
        </span>
        <span>
          {completed} of {summary.total} missions completed
        </span>
      </div>

      {/* Segmented outcome bar — one glance at what happened to each mission */}
      <div
        role="progressbar"
        aria-valuenow={progress}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Overall run progress"
        className="flex w-full h-2.5 gap-[2px] bg-muted/60 rounded-full overflow-hidden"
      >
        {active.map((segment) => (
          <span
            key={segment.key}
            title={`${segment.label}: ${segment.count}`}
            style={{
              width: `${(segment.count / summary.total) * 100}%`,
              minWidth: "4px",
            }}
            className={cn(
                "h-full rounded-full",
                segment.barClass,
                segment.key === "running" && !isTerminalRun && "animate-pulse"
              )}
          />
        ))}
      </div>

      {/* Legend with counts */}
      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5 pt-1">
        {active.length === 0 && (
          <li className="text-xs text-muted-foreground">No missions in this run yet</li>
        )}
        {active.map((segment) => (
          <li
            key={segment.key}
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
            aria-label={`${segment.label}: ${segment.count}`}
          >
            <span className={cn("h-2 w-2 rounded-full shrink-0", segment.dotClass)} />
            <span className="font-medium text-foreground/90">{segment.count}</span>
            <span>{segment.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
