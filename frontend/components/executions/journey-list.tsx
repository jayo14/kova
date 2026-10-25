import type { RunExecutionItem } from "@/lib/api/runs";
import { MaterialIcon } from "@/components/shared/material-icon";
import { isActiveStatus, normalizeExecutionStatus } from "@/lib/executions/status";

const WORKING_STATUSES = ["running", "initializing", "browser_ready", "resuming"];

interface JourneyListProps {
  executions: RunExecutionItem[];
  selectedExecutionId: string | null;
  onSelect: (executionId: string) => void;
}

export function JourneyList({
  executions,
  selectedExecutionId,
  onSelect,
}: JourneyListProps) {
  return (
    <div className="lg:col-span-4 space-y-3">
      <div className="flex items-center justify-between px-1">
        <h2 className="text-sm font-semibold text-foreground tracking-tight">
          Selected Missions ({executions.length})
        </h2>
        <span className="text-xs text-muted-foreground">Click to inspect</span>
      </div>

      <div className="space-y-2 max-h-[700px] overflow-y-auto pr-1">
        {executions.map((item, index) => {
          const isSelected = item.id === selectedExecutionId;
          const normStatus = normalizeExecutionStatus(item.status);
          const isItemActive =
            isActiveStatus(normStatus) && normStatus !== "created" && normStatus !== "queued";
          const isItemWorking = WORKING_STATUSES.includes(normStatus);

          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelect(item.id)}
              className={`w-full text-left p-3.5 rounded-xl border transition-all text-xs space-y-2 ${
                isSelected
                  ? "border-primary bg-primary/5 shadow-sm ring-1 ring-primary/20"
                  : "border-border/60 bg-card/60 hover:bg-muted/40 hover:border-border"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-muted flex items-center justify-center font-mono text-[10px] text-muted-foreground shrink-0">
                    {index + 1}
                  </span>
                  <span className="font-semibold text-foreground line-clamp-1">
                    {item.missionName || "User Journey"}
                  </span>
                </div>

                <span
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium shrink-0 ${
                    normStatus === "completed"
                      ? "bg-emerald-500/10 text-emerald-600"
                      : normStatus === "failed" || normStatus === "error"
                      ? "bg-destructive/10 text-destructive"
                      : isItemActive
                      ? "bg-blue-500/10 text-blue-600"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {isItemWorking && <MaterialIcon name="sync" className="w-3 h-3 animate-spin" />}
                  {normStatus === "completed" && (
                    <MaterialIcon name="check" className="w-3 h-3" />
                  )}
                  {(normStatus === "failed" || normStatus === "error") && (
                    <MaterialIcon name="close" className="w-3 h-3" />
                  )}
                  {normStatus.toUpperCase()}
                </span>
              </div>

              {item.errorMessage && (
                <p className="text-[11px] text-destructive line-clamp-1 pl-7">
                  {item.errorMessage}
                </p>
              )}

              <div className="flex items-center justify-between text-[10px] text-muted-foreground pl-7">
                <span>ID: {item.id.slice(0, 8)}</span>
                {item.durationMs && <span>{(item.durationMs / 1000).toFixed(1)}s</span>}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
