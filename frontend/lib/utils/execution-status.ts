import type { ExecutionStatus } from "@/lib/types";

export interface StatusStyleConfig {
  label: string;
  badgeClass: string;
  dotClass: string;
  iconName: string;
  isAnimated: boolean;
}

export const humanStatusLabels: Record<ExecutionStatus, string> = {
  created: "Preparing execution",
  queued: "Waiting to start",
  initializing: "Preparing Kova",
  browser_ready: "Browser ready",
  running: "Kova is working",
  waiting: "Kova needs something",
  paused: "Kova paused",
  human_controlled: "You have control",
  resuming: "Resuming Kova",
  completed: "Completed",
  failed: "Execution failed",
  cancelled: "Execution cancelled",
  timeout: "Execution timed out",
  blocked: "Mission blocked",
  unverified: "Could not verify",
};

export const humanStatusShortLabels: Record<ExecutionStatus, string> = {
  created: "Preparing",
  queued: "Waiting",
  initializing: "Preparing",
  browser_ready: "Ready",
  running: "Working",
  waiting: "Waiting",
  paused: "Paused",
  human_controlled: "Your control",
  resuming: "Resuming",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  timeout: "Timed out",
  blocked: "Blocked",
  unverified: "Unverified",
};

export function getExecutionStatusConfig(status: ExecutionStatus): StatusStyleConfig {
  switch (status) {
    case "running":
      return {
        label: humanStatusLabels.running,
        badgeClass: "bg-primary/8 text-primary border border-primary/20",
        dotClass: "bg-primary",
        iconName: "play_arrow",
        isAnimated: true,
      };

    case "completed":
      return {
        label: humanStatusLabels.completed,
        badgeClass: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20",
        dotClass: "bg-emerald-600",
        iconName: "check",
        isAnimated: false,
      };

    case "failed":
      return {
        label: humanStatusLabels.failed,
        badgeClass: "bg-destructive/10 text-destructive border border-destructive/20",
        dotClass: "bg-destructive",
        iconName: "error",
        isAnimated: false,
      };

    case "timeout":
      return {
        label: humanStatusLabels.timeout,
        badgeClass: "bg-destructive/10 text-destructive border border-destructive/20",
        dotClass: "bg-destructive",
        iconName: "schedule",
        isAnimated: false,
      };

    case "waiting":
      return {
        label: humanStatusLabels.waiting,
        badgeClass: "bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20",
        dotClass: "bg-amber-600",
        iconName: "pause",
        isAnimated: true,
      };

    case "browser_ready":
      return {
        label: humanStatusLabels.browser_ready,
        badgeClass: "bg-secondary text-foreground border border-border",
        dotClass: "bg-muted-foreground",
        iconName: "laptop",
        isAnimated: false,
      };

    case "queued":
      return {
        label: humanStatusLabels.queued,
        badgeClass: "bg-secondary/60 text-muted-foreground border border-border/60",
        dotClass: "bg-muted-foreground/60",
        iconName: "hourglass_top",
        isAnimated: false,
      };

    case "initializing":
      return {
        label: humanStatusLabels.initializing,
        badgeClass: "bg-secondary/60 text-muted-foreground border border-border/60",
        dotClass: "bg-primary",
        iconName: "sync",
        isAnimated: true,
      };

    case "cancelled":
      return {
        label: humanStatusLabels.cancelled,
        badgeClass: "bg-secondary/40 text-muted-foreground border border-border/40",
        dotClass: "bg-muted-foreground/40",
        iconName: "block",
        isAnimated: false,
      };

    case "paused":
      return {
        label: humanStatusLabels.paused,
        badgeClass: "bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20",
        dotClass: "bg-amber-500",
        iconName: "pause_circle",
        isAnimated: false,
      };

    case "human_controlled":
      return {
        label: humanStatusLabels.human_controlled,
        badgeClass: "bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20",
        dotClass: "bg-amber-500",
        iconName: "person",
        isAnimated: false,
      };

    case "resuming":
      return {
        label: humanStatusLabels.resuming,
        badgeClass: "bg-primary/8 text-primary border border-primary/20",
        dotClass: "bg-primary",
        iconName: "play_circle",
        isAnimated: true,
      };

    case "blocked":
      return {
        label: humanStatusLabels.blocked,
        badgeClass: "bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20",
        dotClass: "bg-amber-600",
        iconName: "lock",
        isAnimated: false,
      };

    case "unverified":
      return {
        label: humanStatusLabels.unverified,
        badgeClass: "bg-orange-500/10 text-orange-700 dark:text-orange-400 border border-orange-500/20",
        dotClass: "bg-orange-600",
        iconName: "help",
        isAnimated: false,
      };

    case "created":
    default:
      return {
        label: humanStatusLabels.created,
        badgeClass: "bg-secondary/40 text-muted-foreground border border-border/40",
        dotClass: "bg-muted-foreground/40",
        iconName: "radio_button_unchecked",
        isAnimated: false,
      };
  }
}
