"use client";

import type { ExecutionDetail } from "@/lib/types";
import type { ExecutionReport } from "@/lib/api/executions";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";

interface ExecutionResultProps {
  execution: ExecutionDetail;
  report?: ExecutionReport | null;
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
    description: "A browser, worker, or internal error stopped reliable verification.",
  },
  blocked: {
    containerClass: "border border-amber-500/20 bg-amber-500/5",
    iconBoxClass: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    icon: "lock",
    title: "Execution blocked",
    titleClass: "text-amber-700 dark:text-amber-400",
    descriptionClass: "text-foreground/80",
    description:
      "Execution was blocked because a required prerequisite, role, or environment condition could not be satisfied.",
  },
  unverified: {
    containerClass: "border border-orange-500/20 bg-orange-500/5",
    iconBoxClass: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
    icon: "help",
    title: "Execution completed without verification",
    titleClass: "text-orange-700 dark:text-orange-400",
    descriptionClass: "text-foreground/80",
    description:
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

function humanizeCategory(category: string): string {
  return category.replaceAll("_", " ");
}

export function ExecutionResult({
  execution,
  report,
  className,
}: ExecutionResultProps) {
  const duration = calculateDuration(execution.startedAt, execution.completedAt);
  const variant = RESULT_VARIANTS[execution.status];

  if (!variant) return null;

  const diagnosis = report?.diagnosis ?? null;
  const explanation = diagnosis?.observed || execution.error || null;
  const nextStep = diagnosis?.nextStep || null;
  const reason = diagnosis?.reason || null;
  const failureCategory = report?.failureCategory || null;
  const errorCode = report?.errorCode || null;

  // Fallback text when no report / execution error is available.
  const fallbackDescription =
    typeof variant.description === "function" ? variant.description(execution) : variant.description;

  const explanationText = explanation || fallbackDescription;
  const nextMessage =
    nextStep || (execution.status === "completed" ? null : fallbackDescription);

  return (
    <section
      aria-label="Execution result"
      className={cn(
        "rounded-2xl p-5 shadow-xs space-y-3",
        variant.containerClass,
        className
      )}
    >
      {/* Headline */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <div
            className={cn(
              "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl",
              variant.iconBoxClass
            )}
          >
            <MaterialIcon name={variant.icon} size={20} className={variant.iconClass} />
          </div>
          <div className="min-w-0">
            <h3 className={cn("text-body-lg font-semibold tracking-tight", variant.titleClass)}>
              {variant.title}
            </h3>

            {/* Error-type tag */}
            {(failureCategory || errorCode) && (
              <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
                {failureCategory && (
                  <span className="inline-flex items-center rounded-md border border-border/60 bg-background/60 px-2 py-0.5 text-caption font-medium uppercase tracking-wide text-foreground/80">
                    {humanizeCategory(failureCategory)}
                  </span>
                )}
                {errorCode && (
                  <span className="inline-flex items-center rounded-md border border-border/60 bg-background/60 px-2 py-0.5 text-caption font-mono text-muted-foreground">
                    {errorCode}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        {duration && (
          <span className="text-caption font-mono text-muted-foreground bg-background/60 px-2.5 py-1 rounded-md border border-border/60 shrink-0">
            {duration}
          </span>
        )}
      </div>

      {/* Plain-language explanation */}
      <p className={cn("text-body-sm leading-relaxed", variant.descriptionClass)}>
        {explanationText}
      </p>

      {/* Next step */}
      {nextMessage && nextMessage !== explanationText && (
        <p className="text-body-sm font-medium text-foreground">
          <span className="font-semibold">Next:</span>{" "}
          <span className="font-normal">{nextMessage}</span>
        </p>
      )}

      {reason && (
        <p className="text-caption text-muted-foreground">{reason}</p>
      )}

      {/* Raw error — collapsed by default so the verdict stays scannable */}
      {execution.error && (
        <details className="group rounded-lg border border-border/60 bg-background/60 overflow-hidden">
          <summary className="flex items-center gap-1.5 px-3 py-2 text-caption font-medium cursor-pointer select-none text-foreground/70 hover:text-foreground transition-colors">
            <MaterialIcon name="code" size={14} className="text-muted-foreground" />
            Technical detail
            <MaterialIcon
              name="expand_more"
              size={14}
              className="ml-auto text-muted-foreground transition-transform group-open:rotate-180"
            />
          </summary>
          <pre className="max-h-40 overflow-auto px-3 py-2.5 text-caption leading-relaxed font-mono whitespace-pre-wrap break-all border-t border-border/40 text-foreground/80">
            {execution.error}
          </pre>
        </details>
      )}
    </section>
  );
}
