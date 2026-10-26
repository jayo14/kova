import type { RunSummary } from "@/lib/api/runs";
import { normalizeRunStatus } from "@/lib/executions/run-status";

interface RunSummaryStatsProps {
  summary: RunSummary;
  progress: number;
  status: string;
}

export function RunSummaryStats({
  summary,
  progress,
  status,
}: RunSummaryStatsProps) {
  const isRunning = normalizeRunStatus(status) === "RUNNING";
  const runStatus = normalizeRunStatus(status);
  const completed = summary.passed + summary.failed + summary.blocked + (summary.unverified || 0);

  return (
    <div className="space-y-2 pt-2 border-t border-border/40">
      <div className="flex items-center justify-between text-xs text-muted-foreground font-medium">
        <span>Overall Progress ({progress}%)</span>
        <span>
          {completed} of {summary.total} completed
        </span>
      </div>
      <div
        role="progressbar"
        aria-valuenow={progress}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Overall run progress"
        className="w-full h-2 bg-muted rounded-full overflow-hidden"
      >
        <div
          className={`h-full transition-all duration-500 rounded-full ${
            runStatus === "FAILED"
              ? "bg-destructive"
              : runStatus === "PASSED"
              ? "bg-emerald-500"
              : "bg-primary"
          }`}
          style={{ width: `${Math.min(100, Math.max(progress, isRunning ? 5 : 0))}%` }}
        />
      </div>

      {/* Metric Badges */}
      <div className="grid grid-cols-2 sm:grid-cols-6 gap-2 pt-2">
        <div className="p-2.5 rounded-lg bg-background/50 border border-border/40 text-center">
          <span className="block text-xs text-muted-foreground">Total Missions</span>
          <span className="text-base font-semibold text-foreground">{summary.total}</span>
        </div>
        <div className="p-2.5 rounded-lg bg-blue-500/5 border border-blue-500/20 text-center">
          <span className="block text-xs text-blue-600">Running</span>
          <span className="text-base font-semibold text-blue-700">{summary.running}</span>
        </div>
        <div className="p-2.5 rounded-lg bg-emerald-500/5 border border-emerald-500/20 text-center">
          <span className="block text-xs text-emerald-600">Passed</span>
          <span className="text-base font-semibold text-emerald-700">{summary.passed}</span>
        </div>
        <div className="p-2.5 rounded-lg bg-destructive/5 border border-destructive/20 text-center">
          <span className="block text-xs text-destructive">Failed</span>
          <span className="text-base font-semibold text-destructive">{summary.failed}</span>
        </div>
        <div className="p-2.5 rounded-lg bg-amber-500/5 border border-amber-500/20 text-center">
          <span className="block text-xs text-amber-600">Blocked</span>
          <span className="text-base font-semibold text-amber-700">{summary.blocked}</span>
        </div>
        <div className="p-2.5 rounded-lg bg-purple-500/5 border border-purple-500/20 text-center">
          <span className="block text-xs text-purple-600">Unverified</span>
          <span className="text-base font-semibold text-purple-700">{summary.unverified ?? 0}</span>
        </div>
      </div>
    </div>
  );
}
