"use client";

import { useEffect, useState, use } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import {
  type Integration,
  type CreateIntegrationInput,
  getProjectIntegrations,
  createProjectIntegration,
  deactivateProjectIntegration,
} from "@/lib/api/integrations";
import { IntegrationCard } from "@/components/integrations/integration-card";
import { IntegrationConnectDialog } from "@/components/integrations/integration-connect-dialog";

export default function ProjectIntegrationsPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = use(params);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchIntegrations = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getProjectIntegrations(projectId);
      setIntegrations(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load integrations");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchIntegrations();
  }, [projectId]);

  const handleConnect = async (input: CreateIntegrationInput) => {
    await createProjectIntegration(projectId, input);
    await fetchIntegrations();
  };

  const handleDisconnect = async (id: string) => {
    try {
      setDeletingId(id);
      await deactivateProjectIntegration(projectId, id);
      setIntegrations((prev) => prev.filter((item) => item.id !== id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to disconnect integration");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="max-w-5xl mx-auto py-8 px-4 sm:px-6 space-y-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-heading-md font-bold text-foreground">Source Control Integrations</h1>
          <p className="text-body-sm text-muted-foreground mt-1">
            Connect GitHub or GitLab repositories to automatically validate every Pull Request.
          </p>
        </div>

        <button
          onClick={() => setDialogOpen(true)}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground font-medium text-caption rounded-lg hover:bg-primary/90 transition-colors shadow-sm"
        >
          <MaterialIcon name="add" size={18} />
          <span>Connect Repository</span>
        </button>
      </div>

      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/20 rounded-xl text-rose-500 text-body-sm">
          {error}
        </div>
      )}

      {/* Integration List */}
      <div className="space-y-4">
        {loading ? (
          <div className="flex items-center justify-center py-16 text-muted-foreground">
            <MaterialIcon name="progress_activity" size={24} className="animate-spin mr-2" />
            <span>Loading integrations...</span>
          </div>
        ) : integrations.length === 0 ? (
          <div className="p-12 text-center border border-dashed border-border rounded-2xl bg-card/40">
            <MaterialIcon name="alt_route" size={48} className="mx-auto mb-3 text-muted-foreground/60" />
            <h3 className="text-body-sm font-semibold text-foreground">No repositories connected</h3>
            <p className="text-caption text-muted-foreground max-w-md mx-auto mt-1 mb-4">
              Connect your repository to have Kova analyze incoming code diffs, run targeted regressions, and post signed reports on PRs.
            </p>
            <button
              onClick={() => setDialogOpen(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground font-medium text-caption rounded-lg hover:bg-primary/90 transition-colors"
            >
              <MaterialIcon name="link" size={16} />
              <span>Connect First Repository</span>
            </button>
          </div>
        ) : (
          integrations.map((item) => (
            <IntegrationCard
              key={item.id}
              integration={item}
              onDelete={handleDisconnect}
              deleting={deletingId === item.id}
            />
          ))
        )}
      </div>

      {/* Webhook Setup Instructions Card */}
      <div className="p-6 bg-card border border-border rounded-xl space-y-3">
        <h3 className="text-body-sm font-semibold text-foreground flex items-center gap-2">
          <MaterialIcon name="info" size={18} className="text-primary" />
          <span>Configuring Webhooks</span>
        </h3>
        <p className="text-caption text-muted-foreground">
          In your GitHub or GitLab repository settings, configure a webhook pointing to:
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[12px] font-mono">
          <div className="p-3 bg-background border border-border rounded-lg">
            <div className="text-muted-foreground text-[10px] uppercase font-sans mb-1 font-semibold">GitHub Payload URL</div>
            <code className="text-primary">POST /api/v1/integrations/github/webhook</code>
          </div>
          <div className="p-3 bg-background border border-border rounded-lg">
            <div className="text-muted-foreground text-[10px] uppercase font-sans mb-1 font-semibold">GitLab Webhook URL</div>
            <code className="text-primary">POST /api/v1/integrations/gitlab/webhook</code>
          </div>
        </div>
      </div>

      <IntegrationConnectDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSubmit={handleConnect}
      />
    </div>
  );
}
