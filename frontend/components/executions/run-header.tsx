import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
import { StatusBadge } from "@/components/shared/status-badge";
import {
  getRunStatusConfig,
  normalizeRunStatus,
} from "@/lib/executions/run-status";

interface RunHeaderProps {
  runId: string;
  status: string;
  isCancelling: boolean;
  onCancel: () => void;
}

export function RunHeader({
  runId,
  status,
  isCancelling,
  onCancel,
}: RunHeaderProps) {
  const runStatus = normalizeRunStatus(status);
  const isRunning = runStatus === "RUNNING";

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <Link
            href="/executions"
            className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            <MaterialIcon name="arrow_back" className="w-3.5 h-3.5" />
            All Runs
          </Link>
          <span className="text-muted-foreground/40" aria-hidden="true">•</span>
          <span className="text-xs font-mono text-muted-foreground">Run #{runId.slice(0, 8)}</span>
        </div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2.5">
          <span>Validation Run Overview</span>
          <StatusBadge
            icon
            config={getRunStatusConfig(runStatus)}
            className="border px-2.5 py-0.5 rounded-full"
          />
        </h1>
      </div>

      <div className="flex items-center gap-2.5">
        {isRunning && (
          <button
            type="button"
            onClick={onCancel}
            disabled={isCancelling}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-destructive hover:bg-destructive/10 border border-destructive/30 transition-colors disabled:opacity-50"
          >
            <MaterialIcon name="stop" className="w-4 h-4" />
            {isCancelling ? "Cancelling..." : "Cancel Run"}
          </button>
        )}
      </div>
    </div>
  );
}
