"use client";

import { useState, useMemo } from "react";
import type { ExecutionDetail, ExecutionStatus } from "@/lib/types";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { ExecutionRow } from "./execution-row";
import { ExecutionEmptyState } from "./execution-empty-state";

interface ExecutionListProps {
  executions: ExecutionDetail[];
}

type FilterValue = ExecutionStatus | "all";

const filterOptions: { label: string; value: FilterValue }[] = [
  { label: "All", value: "all" },
  { label: "Running", value: "running" },
  { label: "Completed", value: "completed" },
  { label: "Failed", value: "failed" },
  { label: "Cancelled", value: "cancelled" },
];

export function ExecutionList({ executions }: ExecutionListProps) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterValue>("all");

  const filtered = useMemo(() => {
    return executions.filter((ex) => {
      // Status filter
      if (filter !== "all") {
        if (filter === "running") {
          // Group active running/queued/initializing states under 'Running'
          if (!["running", "queued", "initializing", "browser_ready", "waiting"].includes(ex.status)) {
            return false;
          }
        } else if (ex.status !== filter) {
          return false;
        }
      }

      // Search query
      if (!search.trim()) return true;
      const q = search.toLowerCase().trim();
      return (
        ex.missionName.toLowerCase().includes(q) ||
        ex.projectName.toLowerCase().includes(q)
      );
    });
  }, [executions, filter, search]);

  if (executions.length === 0) {
    return <ExecutionEmptyState />;
  }

  return (
    <div className="space-y-4">
      {/* Search & Filter Controls */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <MaterialIcon
            name="search"
            size={18}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
          />
          <input
            type="text"
            placeholder="Search executions..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full h-10 rounded-xl border border-input bg-card/60 pl-9 pr-3 text-body-sm text-foreground placeholder:text-muted-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20 transition-colors"
            aria-label="Search executions"
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label="Clear search"
            >
              <MaterialIcon name="close" size={16} />
            </button>
          )}
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0 shrink-0">
          {filterOptions.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setFilter(opt.value)}
              className={`rounded-xl px-3 py-2 text-body-xs font-medium transition-colors cursor-pointer shrink-0 ${
                filter === opt.value
                  ? "bg-primary text-primary-foreground"
                  : "bg-secondary/40 text-muted-foreground hover:bg-secondary/80 hover:text-foreground"
              }`}
              aria-pressed={filter === opt.value}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Results */}
      {filtered.length === 0 ? (
        <div className="rounded-2xl border border-border/80 bg-secondary/10 px-6 py-12 text-center">
          <p className="text-body-sm text-muted-foreground mb-3">
            No executions match your search or filter.
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setSearch("");
              setFilter("all");
            }}
          >
            Clear filters
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {filtered.map((ex) => (
            <ExecutionRow key={ex.id} execution={ex} />
          ))}
        </div>
      )}
    </div>
  );
}
