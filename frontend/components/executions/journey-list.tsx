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
  if (executions.length === 0) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between px-1">
          <h2 className="text-sm font-semibold text-foreground tracking-tight">
            Selected Missions (0)
          </h2>
          <span className="text-xs text-muted-foreground">Click to inspect</span>
        </div>
        <div className="rounded-xl border border-dashed border-border/70 p-6 text-center">
          <p className="text-xs text-muted-foreground">
            No missions in this run.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
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
          const errorText = item.errorMessage || null;

          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelect(item.id)}
              aria-pressed={isSelected}
              className={`w-full min-w-0 text-left p-3.5 rounded-xl border transition-all text-xs space-y-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 ${
                isSelected
                  ? "border-primary bg-primary/5 shadow-sm ring-1 ring-primary/20"
                  : "border-border/60 bg-card/60 hover:bg-muted/40 hover:border-border"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-start gap-2 min-w-0">
                  <span className="w-5 h-5 rounded-full bg-muted flex items-center justify-center font-mono text-[10px] text-muted-foreground shrink-0 mt-px">
                    {index + 1}
                  </span>
                  <span
                    title={item.missionName || "User Journey"}
                    className="font-semibold text-foreground line-clamp-2 leading-snug"
                  >
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

              {errorText && (
                <p
                  title={errorText}
                  className="text-[11px] text-destructive line-clamp-1 pl-7 break-words"
                >
                  {errorText}
                </p>
              )}

              <div className="flex items-center justify-between text-[10px] text-muted-foreground pl-7">
                <span className="truncate">ID: {item.id.slice(0, 8)}</span>
                {item.durationMs && <span>{(item.durationMs / 1000).toFixed(1)}s</span>}
              </div>

              {errorText && (
                <p className="sr-only">{errorText}</p>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
