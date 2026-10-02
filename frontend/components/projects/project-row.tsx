"use client";

import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
import type { ProjectSummary } from "@/lib/types";

interface ProjectRowProps {
  project: ProjectSummary;
}

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

export function ProjectRow({ project }: ProjectRowProps) {
  const counts = [
    project.missionCount != null
      ? `${project.missionCount} mission${project.missionCount !== 1 ? "s" : ""}`
      : null,
    project.executionCount != null
      ? `${project.executionCount} execution${project.executionCount !== 1 ? "s" : ""}`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const displayUrl = project.baseUrl
    ? project.baseUrl.replace(/^https?:\/\//, "").replace(/\/$/, "")
    : "";

  return (
    <Link
      href={`/projects/${project.id}`}
      className="group flex items-center justify-between rounded-xl border border-border/80 bg-card px-4 py-3.5 transition-all duration-200 hover:border-muted-foreground/30 hover:bg-secondary/20 shadow-xs"
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="text-body-sm font-semibold text-foreground truncate group-hover:text-primary transition-colors">
            {project.name}
          </p>
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <p className="text-caption font-mono text-muted-foreground truncate">{displayUrl}</p>
          {project.description && (
            <>
              <span className="text-caption text-muted-foreground/60">·</span>
              <p className="text-caption text-muted-foreground truncate">
                {project.description}
              </p>
            </>
          )}
        </div>
      </div>

      <div className="flex items-center gap-4 ml-4 shrink-0">
        {counts && (
          <span className="text-caption hidden sm:inline">{counts}</span>
        )}
        <span className="text-caption text-muted-foreground hidden md:inline">
          {formatRelativeTime(project.updatedAt)}
        </span>
        <MaterialIcon
          name="chevron_right"
          size={16}
          className="text-muted-foreground group-hover:text-foreground transition-colors"
        />
      </div>
    </Link>
  );
}
