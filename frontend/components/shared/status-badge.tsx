import { cn } from "@/lib/utils";
import {
  getExecutionStatusConfig,
  type StatusStyleConfig,
} from "@/lib/utils/execution-status";
import type { ExecutionStatus } from "@/lib/types";
import { MaterialIcon } from "@/components/shared/material-icon";

interface StatusBadgeProps {
  status?: ExecutionStatus;
  config?: StatusStyleConfig;
  className?: string;
  /** Render the status icon instead of the dot (used by run header). */
  icon?: boolean;
}

export function StatusBadge({ status, config, className, icon }: StatusBadgeProps) {
  const resolved = config ?? (status ? getExecutionStatusConfig(status) : null);
  if (!resolved) return null;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-caption font-medium select-none",
        resolved.badgeClass,
        className
      )}
    >
      {icon ? (
        <MaterialIcon
          name={resolved.iconName}
          className={cn("w-3.5 h-3.5 shrink-0", resolved.isAnimated && "animate-spin")}
        />
      ) : (
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full shrink-0",
            resolved.dotClass,
            resolved.isAnimated && "animate-pulse"
          )}
        />
      )}
      <span className="truncate">{resolved.label}</span>
    </span>
  );
}
