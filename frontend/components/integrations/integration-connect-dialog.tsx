"use client";

import { useState } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import type { CreateIntegrationInput } from "@/lib/api/integrations";

interface IntegrationConnectDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (data: CreateIntegrationInput) => Promise<void>;
}

export function IntegrationConnectDialog({
  open,
  onClose,
  onSubmit,
}: IntegrationConnectDialogProps) {
  const [provider, setProvider] = useState<"github" | "gitlab">("github");
  const [repoId, setRepoId] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [defaultBranch, setDefaultBranch] = useState("main");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!repoId.trim() || !webhookSecret.trim()) {
      setError("Repository identifier and Webhook Secret are required");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await onSubmit({
        provider,
        provider_repo_id: repoId.trim(),
        webhook_secret: webhookSecret.trim(),
        access_token: accessToken.trim() || undefined,
        default_branch: defaultBranch.trim() || "main",
        kova_config_path: ".kova.yml",
      });
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to connect integration");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/75 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-card border border-border rounded-2xl shadow-2xl overflow-hidden z-10">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-2">
            <MaterialIcon name="link" size={20} className="text-primary" />
            <h3 className="text-body-sm font-semibold text-foreground">Connect Git Repository</h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground"
          >
            <MaterialIcon name="close" size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="p-3 text-caption text-rose-500 bg-rose-500/10 border border-rose-500/20 rounded-lg">
              {error}
            </div>
          )}

          {/* Provider Selection */}
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => setProvider("github")}
              className={`p-3 rounded-xl border flex items-center justify-center gap-2 font-medium text-caption transition-all ${
                provider === "github"
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border hover:bg-muted/40 text-muted-foreground"
              }`}
            >
              <span>GitHub</span>
            </button>
            <button
              type="button"
              onClick={() => setProvider("gitlab")}
              className={`p-3 rounded-xl border flex items-center justify-center gap-2 font-medium text-caption transition-all ${
                provider === "gitlab"
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border hover:bg-muted/40 text-muted-foreground"
              }`}
            >
              <span>GitLab</span>
            </button>
          </div>

          <div>
            <label className="block text-caption font-medium text-foreground mb-1">
              {provider === "github" ? "GitHub Repository (owner/repo)" : "GitLab Project (ID or namespace/project)"}
            </label>
            <input
              type="text"
              value={repoId}
              onChange={(e) => setRepoId(e.target.value)}
              placeholder={provider === "github" ? "octocat/hello-world" : "gitlab-org/gitlab"}
              className="w-full px-3 py-2 bg-background border border-border rounded-lg text-body-sm focus:outline-none focus:border-primary"
              required
            />
          </div>

          <div>
            <label className="block text-caption font-medium text-foreground mb-1">Webhook Secret</label>
            <input
              type="password"
              value={webhookSecret}
              onChange={(e) => setWebhookSecret(e.target.value)}
              placeholder="Configured HMAC / GitLab secret token"
              className="w-full px-3 py-2 bg-background border border-border rounded-lg text-body-sm focus:outline-none focus:border-primary"
              required
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              Used to cryptographically verify incoming PR/MR webhooks.
            </p>
          </div>

          <div>
            <label className="block text-caption font-medium text-foreground mb-1">
              Access Token (optional for comment posting & private repos)
            </label>
            <input
              type="password"
              value={accessToken}
              onChange={(e) => setAccessToken(e.target.value)}
              placeholder="ghp_... or glpat-..."
              className="w-full px-3 py-2 bg-background border border-border rounded-lg text-body-sm focus:outline-none focus:border-primary"
            />
          </div>

          <div>
            <label className="block text-caption font-medium text-foreground mb-1">Default Branch</label>
            <input
              type="text"
              value={defaultBranch}
              onChange={(e) => setDefaultBranch(e.target.value)}
              placeholder="main"
              className="w-full px-3 py-2 bg-background border border-border rounded-lg text-body-sm focus:outline-none focus:border-primary"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-caption font-medium text-muted-foreground hover:text-foreground rounded-lg"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 text-caption font-medium bg-primary text-primary-foreground hover:bg-primary/90 rounded-lg transition-colors disabled:opacity-50"
            >
              {submitting ? "Connecting..." : "Connect Repository"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
