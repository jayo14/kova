"use client";

import type { ExecutionDetail } from "@/lib/types";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";

interface ExecutionResultProps {
  execution: ExecutionDetail;
  className?: string;
}

interface ResultVariant {
  containerClass: string;
  iconBoxClass: string;
  icon: string;
  iconClass?: string;
  title: string;
  titleClass: string;
  descriptionClass: string;
  description: string | ((execution: ExecutionDetail) => string);
}

const RESULT_VARIANTS: Record<string, ResultVariant> = {
  completed: {
    containerClass: "border border-emerald-500/20 bg-emerald-500/5",
    iconBoxClass: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    icon: "check_circle",
    title: "Mission completed",
    titleClass: "text-emerald-700 dark:text-emerald-400",
    descriptionClass: "text-foreground/80",
    description: "Kova accomplished the mission and verified application state.",
  },
  failed: {
    containerClass: "border border-destructive/20 bg-destructive/5",
    iconBoxClass: "bg-destructive/10 text-destructive",
    icon: "error",
    title: "Execution failed",
    titleClass: "text-destructive",
    descriptionClass: "text-foreground/80",
    description: (execution) => execution.error || "Kova couldn't complete this mission.",
  },
  error: {
    containerClass: "border border-orange-500/20 bg-orange-500/5",
    iconBoxClass: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
    icon: "warning",
    iconClass: "text-orange-600",
    title: "Execution could not be completed reliably",
    titleClass: "text-orange-700 dark:text-orange-400",
    descriptionClass: "text-foreground/80",
    description: (execution) =>
      execution.error || "A browser, worker, or internal error stopped reliable verification.",
  },
  blocked: {
    containerClass: "border border-amber-500/20 bg-amber-500/5",
    iconBoxClass: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    icon: "lock",
    title: "Execution blocked",
    titleClass: "text-amber-700 dark:text-amber-400",
    descriptionClass: "text-foreground/80",
    description: (execution) =>
      execution.error ||
      "Execution was blocked because a required prerequisite, role, or environment condition could not be satisfied.",
  },
  unverified: {
    containerClass: "border border-orange-500/20 bg-orange-500/5",
    iconBoxClass: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
    icon: "help",
    title: "Execution completed without verification",
    titleClass: "text-orange-700 dark:text-orange-400",
    descriptionClass: "text-foreground/80",
    description: (execution) =>
      execution.error ||
      "The actions were performed, but available evidence was insufficient to verify the intended business outcomes.",
  },
  timeout: {
    containerClass: "border border-destructive/20 bg-destructive/5",
    iconBoxClass: "bg-destructive/10 text-destructive",
    icon: "timer_off",
    title: "Execution timed out",
    titleClass: "text-destructive",
    descriptionClass: "text-foreground/80",
    description: "Kova couldn't complete the mission within the allowed time.",
  },
  cancelled: {
    containerClass: "border border-border/80 bg-secondary/20",
    iconBoxClass: "bg-secondary text-muted-foreground",
    icon: "cancel",
    title: "Execution cancelled",
    titleClass: "text-foreground",
    descriptionClass: "text-muted-foreground",
    description: "Kova stopped this execution.",
  },
};

function calculateDuration(startedAt?: string | null, completedAt?: string | null): string | null {
  if (!startedAt || !completedAt) return null;
  try {
    const start = new Date(startedAt).getTime();
    const end = new Date(completedAt).getTime();
    const diff = end - start;
    if (diff < 0) return null;
    return `${(diff / 1000).toFixed(1)}s`;
  } catch {
    return null;
  }
}

export function ExecutionResult({
  execution,
  className,
}: ExecutionResultProps) {
  const duration = calculateDuration(execution.startedAt, execution.completedAt);
  const variant = RESULT_VARIANTS[execution.status];

  if (!variant) return null;

  const description =
    typeof variant.description === "function"
      ? variant.description(execution)
      : variant.description;

  return (
    <section
      aria-label="Execution result"
      className={cn(
        "rounded-2xl p-5 shadow-xs space-y-4",
        variant.containerClass,
        className
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div
            className={cn(
              "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl",
              variant.iconBoxClass
            )}
          >
            <MaterialIcon name={variant.icon} size={20} className={variant.iconClass} />
          </div>
          <div>
            <h3 className={cn("text-body font-semibold", variant.titleClass)}>
              {variant.title}
            </h3>
            <p
              className={cn(
                "text-body-sm mt-0.5 leading-relaxed",
                variant.descriptionClass
              )}
            >
              {description}
            </p>
          </div>
        </div>

        {duration && (
          <span className="text-caption font-mono text-muted-foreground bg-background/60 px-2.5 py-1 rounded-md border border-border/60 shrink-0">
            {duration}
          </span>
        )}
      </div>
    </section>
  );
}
