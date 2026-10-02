import { MaterialIcon } from "@/components/shared/material-icon";
import type { Project } from "@/lib/types";

interface ProjectOverviewProps {
  project: Project;
}

function formatUrl(url: string): string {
  try {
    return new URL(url.startsWith("http") ? url : `https://${url}`).hostname;
  } catch {
    return url;
  }
}

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

export function ProjectOverview({ project }: ProjectOverviewProps) {
  const displayUrl = project.baseUrl.startsWith("http")
    ? project.baseUrl
    : `https://${project.baseUrl}`;

  return (
    <section
      aria-label="Product overview"
      className="rounded-2xl border border-border/80 bg-card/60 p-6 shadow-xs"
    >
      <h2 className="text-body-sm font-semibold text-foreground mb-3">
        About this product
      </h2>

      {project.description ? (
        <p className="text-body-sm text-foreground/80 leading-relaxed mb-5">
          {project.description}
        </p>
      ) : (
        <p className="text-body-sm text-muted-foreground italic mb-5">
          No description provided yet.
        </p>
      )}

      <div className="space-y-2.5 border-t border-border/60 pt-4">
        <div className="flex items-center gap-2.5 text-body-sm">
          <MaterialIcon
            name="public"
            size={16}
            className="text-muted-foreground/80 shrink-0"
          />
          <span className="text-muted-foreground">Canonical URL:</span>
          <a
            href={displayUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 font-medium text-primary hover:text-primary/80 transition-colors"
          >
            <span>{formatUrl(project.baseUrl)}</span>
            <MaterialIcon name="open_in_new" size={13} className="opacity-70" />
          </a>
        </div>

        <div className="flex items-center gap-2.5 text-body-sm">
          <MaterialIcon
            name="calendar_today"
            size={16}
            className="text-muted-foreground/80 shrink-0"
          />
          <span className="text-muted-foreground">
            Discovered by Kova on {formatDate(project.createdAt)}
          </span>
        </div>
      </div>
    </section>
  );
}
