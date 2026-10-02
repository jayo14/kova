"use client";

import { useState } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { ProjectRow } from "./project-row";
import { ProjectEmptyState } from "./project-empty-state";
import type { ProjectSummary } from "@/lib/types";

interface ProjectListProps {
  projects: ProjectSummary[];
  showSearch?: boolean;
}

export function ProjectList({ projects, showSearch = true }: ProjectListProps) {
  const [query, setQuery] = useState("");

  if (projects.length === 0) {
    return <ProjectEmptyState />;
  }

  const filtered = projects.filter((p) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      p.name.toLowerCase().includes(q) ||
      p.baseUrl.toLowerCase().includes(q) ||
      (p.description?.toLowerCase().includes(q) ?? false)
    );
  });

  return (
    <div>
      {showSearch && (
        <div className="relative mb-6">
          <MaterialIcon
            name="search"
            size={18}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
          />
          <input
            type="text"
            placeholder="Search projects..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full h-10 rounded-lg border border-input bg-background pl-9 pr-3 text-body-sm text-foreground placeholder:text-muted-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20 transition-colors"
            aria-label="Search projects"
          />
        </div>
      )}

      {filtered.length === 0 ? (
        <p className="text-body-sm text-muted-foreground text-center py-12">
          No projects match your search.
        </p>
      ) : (
        <div className="flex flex-col gap-1">
          {filtered.map((project) => (
            <ProjectRow key={project.id} project={project} />
          ))}
        </div>
      )}
    </div>
  );
}
