import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
import type { ProjectActivity as Activity } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ProjectActivityProps {
  activities: Activity[];
}

function activityConfig(type: Activity["type"]) {
  switch (type) {
    case "mission_completed":
    case "execution_completed":
      return {
        icon: "check_circle",
        iconClass: "text-emerald-600 dark:text-emerald-400",
        containerClass: "bg-emerald-500/10 border-emerald-500/20",
        label: "Completed",
      };
    case "mission_failed":
    case "execution_failed":
      return {
        icon: "error",
        iconClass: "text-destructive",
        containerClass: "bg-destructive/10 border-destructive/20",
        label: "Failed",
      };
    case "mission_created":
      return {
        icon: "add_circle",
        iconClass: "text-primary",
        containerClass: "bg-primary/10 border-primary/20",
        label: "Mission created",
      };
    default:
      return {
        icon: "radio_button_checked",
        iconClass: "text-muted-foreground",
        containerClass: "bg-secondary border-border/80",
        label: "Activity",
      };
  }
}

function formatRelativeTime(dateStr: string): string {
  try {
    const diff = Date.now() - new Date(dateStr).getTime();
    const minutes = Math.floor(diff / 60000);
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days === 1) return "yesterday";
    if (days < 30) return `${days}d ago`;
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  } catch {
    return dateStr;
  }
}

export function ProjectActivity({ activities }: ProjectActivityProps) {
  if (activities.length === 0) {
    return (
      <section
        aria-label="Recent activity"
        className="rounded-2xl border border-border/80 bg-card/60 p-6 shadow-xs"
      >
        <h2 className="text-body-sm font-semibold text-foreground mb-3">
          Recent activity
        </h2>
        <p className="text-body-sm text-muted-foreground leading-relaxed">
          No activity yet. Run a mission to see results here.
        </p>
      </section>
    );
  }

  return (
    <section
      aria-label="Recent activity"
      className="rounded-2xl border border-border/80 bg-card/60 p-6 shadow-xs"
    >
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-body-sm font-semibold text-foreground">
          Recent activity
        </h2>
        <span className="inline-flex items-center rounded-full bg-secondary/60 px-2.5 py-0.5 text-caption font-medium text-muted-foreground">
          {activities.length}
        </span>
      </div>

      <div className="relative space-y-4 before:absolute before:left-4 before:top-2 before:bottom-2 before:w-[1px] before:bg-border/60">
        {activities.map((activity) => {
          const config = activityConfig(activity.type);
          const targetHref = activity.executionId
            ? `/executions/${activity.executionId}`
            : activity.missionId
            ? `/flows/${activity.missionId}`
            : null;

          const content = (
            <div className="group relative flex items-start gap-3.5 pl-1">
              <div
                className={cn(
                  "relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border",
                  config.containerClass
                )}
              >
                <MaterialIcon
                  name={config.icon}
                  size={15}
                  className={config.iconClass}
                />
              </div>

              <div className="min-w-0 flex-1 pt-0.5">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-body-sm font-medium text-foreground group-hover:text-primary transition-colors truncate">
                    {activity.title}
                  </p>
                  <span className="text-caption text-muted-foreground shrink-0">
                    {formatRelativeTime(activity.createdAt)}
                  </span>
                </div>

                {activity.description && (
                  <p className="text-caption text-muted-foreground mt-0.5 line-clamp-2">
                    {activity.description}
                  </p>
                )}
              </div>
            </div>
          );

          if (targetHref) {
            return (
              <Link
                key={activity.id}
                href={targetHref}
                className="block hover:opacity-90 transition-opacity"
              >
                {content}
              </Link>
            );
          }

          return <div key={activity.id}>{content}</div>;
        })}
      </div>
    </section>
  );
}
