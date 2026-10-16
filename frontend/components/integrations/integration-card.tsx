"use client";

import { MaterialIcon } from "@/components/shared/material-icon";
import type { Integration } from "@/lib/api/integrations";

interface IntegrationCardProps {
  integration: Integration;
  onDelete: (id: string) => void;
  deleting?: boolean;
}

export function IntegrationCard({
  integration,
  onDelete,
  deleting = false,
}: IntegrationCardProps) {
  const isGithub = integration.provider === "github";

  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between p-5 bg-card border border-border rounded-xl shadow-sm gap-4 transition-all hover:border-primary/40">
      <div className="flex items-start sm:items-center gap-4 min-w-0">
        <div
          className={`h-11 w-11 rounded-xl flex items-center justify-center shrink-0 text-white font-bold text-sm ${
            isGithub ? "bg-[#24292e]" : "bg-[#fc6d26]"
          }`}
        >
          {isGithub ? "GH" : "GL"}
        </div>

        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h4 className="text-body-sm font-semibold text-foreground truncate">
              {integration.providerRepoId}
            </h4>
            <span
              className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${
                integration.active
                  ? "bg-emerald-500/10 text-emerald-500 border border-emerald-500/20"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              {integration.active ? "Active" : "Inactive"}
            </span>
          </div>

          <p className="text-[12px] text-muted-foreground mt-1 flex items-center gap-3">
            <span>Branch: <code className="font-mono text-foreground">{integration.defaultBranch}</code></span>
            <span>&bull;</span>
            <span>Config: <code className="font-mono text-foreground">{integration.kovaConfigPath}</code></span>
            <span>&bull;</span>
            <span>Added {new Date(integration.createdAt).toLocaleDateString()}</span>
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 self-end sm:self-center">
        <button
          onClick={() => onDelete(integration.id)}
          disabled={deleting}
          className="flex items-center gap-1.5 px-3 py-1.5 text-caption font-medium rounded-lg text-rose-500 hover:bg-rose-500/10 transition-colors disabled:opacity-50"
        >
          <MaterialIcon name="delete" size={16} />
          <span>{deleting ? "Disconnecting..." : "Disconnect"}</span>
        </button>
      </div>
    </div>
  );
}
