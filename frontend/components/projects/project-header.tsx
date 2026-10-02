"use client";

import { useState } from "react";
import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button, buttonVariants } from "@/components/ui/button";
import type { Project } from "@/lib/types";
import { ProjectSettingsDialog } from "./project-settings";
import { cn } from "@/lib/utils";

interface ProjectHeaderProps {
  project: Project;
  missionCount?: number;
  onProjectUpdated?: (updated: Project) => void;
}

function formatUrl(url: string): string {
  try {
    return new URL(url.startsWith("http") ? url : `https://${url}`).hostname;
  } catch {
    return url;
  }
}

export function ProjectHeader({
  project,
  missionCount,
  onProjectUpdated,
}: ProjectHeaderProps) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [currentProject, setCurrentProject] = useState(project);

  return (
    <div className="mb-8">
      <nav
        aria-label="Breadcrumb"
        className="mb-4 flex items-center gap-1.5 text-body-sm text-muted-foreground"
      >
        <Link
          href="/projects"
          className="inline-flex items-center gap-1 hover:text-foreground transition-colors"
        >
          <MaterialIcon name="arrow_back" size={16} />
          <span>Products</span>
        </Link>
        <span className="text-border">/</span>
        <span className="text-foreground font-medium truncate max-w-[200px] sm:max-w-xs">
          {currentProject.name}
        </span>
      </nav>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-h1 text-foreground mb-1.5 truncate">
            {currentProject.name}
          </h1>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-body-sm text-muted-foreground">
            <a
              href={currentProject.baseUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 hover:text-foreground transition-colors underline-offset-4 hover:underline"
            >
              <span>{formatUrl(currentProject.baseUrl)}</span>
              <MaterialIcon name="open_in_new" size={14} className="opacity-70" />
            </a>
            {currentProject.description && (
              <>
                <span aria-hidden="true">·</span>
                <span className="truncate max-w-md">{currentProject.description}</span>
              </>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSettingsOpen(true)}
            className="gap-1.5 rounded-xl border-border/80 text-foreground hover:bg-secondary/40"
          >
            <MaterialIcon
              name="settings"
              size={16}
              className="text-muted-foreground"
            />
            <span className="hidden sm:inline">Settings</span>
          </Button>

          {missionCount != null && missionCount > 0 ? (
            <Link
              href={`/flows?projectId=${currentProject.id}`}
              className={cn(
                buttonVariants({ variant: "default", size: "sm" }),
                "gap-1.5 rounded-xl font-medium shadow-sm"
              )}
            >
              <span>Run a mission</span>
              <MaterialIcon name="arrow_forward" size={16} />
            </Link>
          ) : (
            <Link
              href={`/explore?projectId=${currentProject.id}&url=${encodeURIComponent(currentProject.baseUrl)}`}
              className={cn(
                buttonVariants({ variant: "default", size: "sm" }),
                "gap-1.5 rounded-xl font-medium shadow-sm"
              )}
            >
              <span>Explore product</span>
              <MaterialIcon name="arrow_forward" size={16} />
            </Link>
          )}
        </div>
      </div>

      <ProjectSettingsDialog
        project={currentProject}
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        onProjectUpdated={(updated) => {
          setCurrentProject(updated);
          onProjectUpdated?.(updated);
        }}
      />
    </div>
  );
}
