"use client";

import { useState, useMemo } from "react";
import type { Mission, MissionExecution } from "@/lib/types";
import { MissionRow } from "./mission-row";
import { FlowEmptyState } from "./flow-empty-state";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";

interface MissionListProps {
  missions: Mission[];
  executions: Map<string, MissionExecution>;
  executionCounts?: Map<string, number>;
  initialProjectId?: string;
  projects?: Array<{ id: string; name: string }>;
}

export function MissionList({
  missions,
  executions,
  executionCounts,
  initialProjectId,
  projects: providedProjects,
}: MissionListProps) {
  const [query, setQuery] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState<string>(
    initialProjectId || "all"
  );

  // Derive available projects
  const projects = useMemo(() => {
    if (providedProjects && providedProjects.length > 0) {
      return providedProjects;
    }
    const map = new Map<string, string>();
    for (const m of missions) {
      if (m.projectId && m.projectName) {
        map.set(m.projectId, m.projectName);
      }
    }
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [missions, providedProjects]);

  // Filter missions
  const filtered = useMemo(() => {
    return missions.filter((m) => {
      // Project filter
      if (selectedProjectId !== "all" && m.projectId !== selectedProjectId) {
        return false;
      }

      // Search query
      if (!query.trim()) return true;
      const q = query.toLowerCase().trim();
      return (
        m.name.toLowerCase().includes(q) ||
        m.projectName.toLowerCase().includes(q) ||
        m.objective.toLowerCase().includes(q) ||
        (m.description?.toLowerCase().includes(q) ?? false)
      );
    });
  }, [missions, selectedProjectId, query]);

  if (missions.length === 0) {
    return (
      <FlowEmptyState
        projectId={selectedProjectId !== "all" ? selectedProjectId : undefined}
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* Search & Project Filter Controls */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <MaterialIcon
            name="search"
            size={18}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
          />
          <input
            type="text"
            placeholder="Search missions..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full h-10 rounded-xl border border-input bg-card/60 pl-9 pr-3 text-body-sm text-foreground placeholder:text-muted-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20 transition-colors"
            aria-label="Search missions"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label="Clear search"
            >
              <MaterialIcon name="close" size={16} />
            </button>
          )}
        </div>

        {projects.length > 1 && (
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0 shrink-0">
            <button
              type="button"
              onClick={() => setSelectedProjectId("all")}
              className={`rounded-xl px-3 py-2 text-body-xs font-medium transition-colors cursor-pointer shrink-0 ${
                selectedProjectId === "all"
                  ? "bg-primary text-primary-foreground"
                  : "bg-secondary/40 text-muted-foreground hover:bg-secondary/80 hover:text-foreground"
              }`}
            >
              All products
            </button>
            {projects.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => setSelectedProjectId(p.id)}
                className={`rounded-xl px-3 py-2 text-body-xs font-medium transition-colors cursor-pointer shrink-0 ${
                  selectedProjectId === p.id
                    ? "bg-primary text-primary-foreground"
                    : "bg-secondary/40 text-muted-foreground hover:bg-secondary/80 hover:text-foreground"
                }`}
              >
                {p.name}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Results */}
      {filtered.length === 0 ? (
        <div className="rounded-2xl border border-border/80 bg-secondary/10 px-6 py-12 text-center">
          <p className="text-body-sm text-muted-foreground mb-3">
            No missions match your search or filter.
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setQuery("");
              setSelectedProjectId("all");
            }}
          >
            Clear filters
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {filtered.map((mission) => {
            const lastExec = executions.get(mission.id) ?? null;
            const count = executionCounts?.get(mission.id);
            return (
              <MissionRow
                key={mission.id}
                mission={mission}
                lastExecution={lastExec}
                executionCount={count}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
