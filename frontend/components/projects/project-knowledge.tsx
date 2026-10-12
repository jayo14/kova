"use client";

import React from "react";
import type { ProductModel } from "@/lib/types";
import { MaterialIcon } from "@/components/ui/material-icon";

interface ProjectKnowledgeProps {
  knowledge: ProductModel | null;
}

export function ProjectKnowledge({ knowledge }: ProjectKnowledgeProps) {
  if (!knowledge) {
    return (
      <div className="rounded-xl border border-border bg-card/40 p-5 text-center">
        <MaterialIcon name="psychology" size={24} className="mx-auto text-muted-foreground mb-2" />
        <h3 className="text-body font-semibold">Product Knowledge Initializing</h3>
        <p className="text-body-sm text-muted-foreground mt-1">
          Explore or validate this application once to seed persistent capabilities and route maps.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card/40 p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <MaterialIcon name="auto_awesome" size={20} className="text-primary" />
          <h3 className="text-body font-semibold text-foreground">Persistent Product Model</h3>
        </div>
        <span className="text-caption font-mono rounded-md border border-border px-2 py-0.5 text-muted-foreground">
          Version {knowledge.version}
        </span>
      </div>

      {knowledge.purpose && (
        <p className="text-body-sm text-muted-foreground leading-relaxed">
          {knowledge.purpose}
        </p>
      )}

      {/* Discovered Capabilities */}
      <div className="space-y-2">
        <h4 className="text-caption font-semibold uppercase tracking-wider text-muted-foreground">
          Discovered Capabilities ({knowledge.capabilities.length})
        </h4>
        <div className="grid gap-2 sm:grid-cols-2">
          {knowledge.capabilities.map((cap, i) => (
            <div key={i} className="rounded-lg border border-border/80 bg-background/50 p-3 space-y-1">
              <div className="flex items-center justify-between gap-1">
                <span className="text-body-sm font-medium text-foreground">{cap.name}</span>
                <span className="text-caption text-muted-foreground">
                  {cap.is_inferred ? "inferred" : "verified"}
                </span>
              </div>
              {cap.description && (
                <p className="text-caption text-muted-foreground line-clamp-2">{cap.description}</p>
              )}
              {cap.routes && cap.routes.length > 0 && (
                <div className="flex flex-wrap gap-1 pt-1">
                  {cap.routes.map((r, rIdx) => (
                    <span key={rIdx} className="font-mono text-[11px] rounded bg-secondary px-1.5 py-0.5 text-secondary-foreground">
                      {r}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Roles & Boundaries */}
      {knowledge.roles && knowledge.roles.length > 0 && (
        <div className="pt-2 border-t border-border/60">
          <span className="text-caption font-medium text-muted-foreground">Observed Roles: </span>
          <span className="text-caption text-foreground">
            {knowledge.roles.map((r) => r.role).join(", ")}
          </span>
        </div>
      )}
    </div>
  );
}
