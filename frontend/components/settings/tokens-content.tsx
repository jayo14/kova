"use client";

import { useEffect, useState } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  createToken,
  deleteToken,
  listTokens,
  type ApiToken,
} from "@/lib/api/tokens";

const AVAILABLE_SCOPES = [
  { id: "ci:validate", label: "ci:validate (Trigger CI runs & continuous validation)" },
  { id: "projects:read", label: "projects:read (View flows, projects, and graphs)" },
  { id: "org:manage", label: "org:manage (Manage members and organization settings)" },
  { id: "*", label: "* (Full administrative access)" },
];

export function TokensContent() {
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [selectedScopes, setSelectedScopes] = useState<string[]>(["ci:validate"]);
  const [rawTokenCreated, setRawTokenCreated] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [creating, setCreating] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const loadTokens = async () => {
    setLoading(true);
    try {
      const data = await listTokens();
      setTokens(data);
    } catch (err: any) {
      console.error("Failed to load tokens", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTokens();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      const created = await createToken(
        name.trim(),
        selectedScopes.length > 0 ? selectedScopes : ["*"]
      );
      if (created.token) {
        setRawTokenCreated(created.token);
      }
      setName("");
      setSelectedScopes(["ci:validate"]);
      setDialogOpen(false);
      await loadTokens();
    } catch (err: any) {
      alert(err.message || "Failed to create API token");
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (id: string) => {
    if (!confirm("Are you sure you want to revoke this API token? Any CI jobs using it will immediately fail.")) {
      return;
    }
    setRevokingId(id);
    try {
      await deleteToken(id);
      await loadTokens();
    } catch (err: any) {
      alert(err.message || "Failed to revoke token");
    } finally {
      setRevokingId(null);
    }
  };

  const handleCopy = () => {
    if (rawTokenCreated) {
      navigator.clipboard.writeText(rawTokenCreated);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    }
  };

  const toggleScope = (scopeId: string) => {
    if (selectedScopes.includes(scopeId)) {
      setSelectedScopes(selectedScopes.filter((s) => s !== scopeId));
    } else {
      setSelectedScopes([...selectedScopes, scopeId]);
    }
  };

  return (
    <div className="space-y-8 max-w-5xl mx-auto py-4">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border/60 pb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">API Tokens</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Generate and manage scoped API tokens for GitHub Actions, GitLab CI, or programmatic API access.
          </p>
        </div>
        <div>
          <Button onClick={() => setDialogOpen(true)} className="flex items-center gap-2">
            <MaterialIcon name="add" size={16} />
            Generate New Token
          </Button>
        </div>
      </div>

      {/* One-time token reveal banner */}
      {rawTokenCreated && (
        <div className="p-5 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-950 dark:text-amber-200 space-y-3 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-2 font-semibold">
              <MaterialIcon name="warning" size={20} className="text-amber-500" />
              <span>Make sure to copy your API token now!</span>
            </div>
            <button
              onClick={() => setRawTokenCreated(null)}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Dismiss
            </button>
          </div>
          <p className="text-xs text-muted-foreground">
            You won&apos;t be able to see this token again. If you lose it, you will need to revoke it and generate a new one.
          </p>
          <div className="flex items-center gap-2 pt-1">
            <div className="font-mono text-xs p-2.5 bg-background border border-border/80 rounded-xl flex-1 select-all overflow-x-auto text-foreground">
              {rawTokenCreated}
            </div>
            <Button size="sm" variant="outline" onClick={handleCopy} className="flex items-center gap-1.5 shrink-0">
              <MaterialIcon name={copied ? "check" : "content_copy"} size={14} />
              {copied ? "Copied!" : "Copy"}
            </Button>
          </div>
        </div>
      )}

      {/* Create Dialog Modal */}
      {dialogOpen && (
        <div className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-card border border-border/80 rounded-2xl shadow-xl max-w-lg w-full p-6 space-y-5 animate-in fade-in zoom-in-95">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold">Generate New API Token</h2>
              <button
                onClick={() => setDialogOpen(false)}
                className="text-muted-foreground hover:text-foreground"
              >
                <MaterialIcon name="close" size={20} />
              </button>
            </div>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Token Name / Description</label>
                <Input
                  placeholder="e.g. GitHub Actions CI Token"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium">Permission Scopes</label>
                <div className="space-y-2 border border-border/60 rounded-xl p-3 bg-secondary/20">
                  {AVAILABLE_SCOPES.map((scope) => (
                    <label
                      key={scope.id}
                      className="flex items-center gap-2.5 text-xs cursor-pointer select-none py-1"
                    >
                      <input
                        type="checkbox"
                        checked={selectedScopes.includes(scope.id)}
                        onChange={() => toggleScope(scope.id)}
                        className="rounded border-border text-primary focus:ring-primary h-4 w-4"
                      />
                      <span className="font-mono text-foreground font-medium">{scope.label}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <Button type="button" variant="ghost" onClick={() => setDialogOpen(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={creating || !name.trim()}>
                  {creating ? "Generating..." : "Generate Token"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Tokens List */}
      <div className="border border-border/70 rounded-2xl bg-card/40 p-6 space-y-4">
        <h2 className="text-lg font-semibold tracking-tight">Active Tokens</h2>
        {loading ? (
          <div className="py-8 text-center text-sm text-muted-foreground">Loading tokens...</div>
        ) : tokens.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted-foreground">
            No API tokens generated yet. Click &quot;Generate New Token&quot; above to create one for CI/CD.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="text-xs uppercase text-muted-foreground border-b border-border/60">
                <tr>
                  <th className="py-2.5 px-3">Name</th>
                  <th className="py-2.5 px-3">Scopes</th>
                  <th className="py-2.5 px-3">Created</th>
                  <th className="py-2.5 px-3">Last Used</th>
                  <th className="py-2.5 px-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {tokens.map((tok) => (
                  <tr key={tok.id} className="hover:bg-muted/30 transition-colors">
                    <td className="py-3 px-3 font-medium text-foreground">{tok.name}</td>
                    <td className="py-3 px-3">
                      <div className="flex flex-wrap gap-1">
                        {tok.scopes?.map((s) => (
                          <Badge key={s} variant="secondary" className="font-mono text-[11px] px-1.5 py-0">
                            {s}
                          </Badge>
                        ))}
                      </div>
                    </td>
                    <td className="py-3 px-3 text-muted-foreground font-mono text-xs">
                      {new Date(tok.created_at).toLocaleDateString()}
                    </td>
                    <td className="py-3 px-3 text-muted-foreground font-mono text-xs">
                      {tok.last_used_at ? new Date(tok.last_used_at).toLocaleDateString() : "Never"}
                    </td>
                    <td className="py-3 px-3 text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleRevoke(tok.id)}
                        disabled={revokingId === tok.id}
                        className="text-destructive hover:text-destructive hover:bg-destructive/10 text-xs h-8 px-2.5"
                      >
                        <MaterialIcon name="delete" size={14} className="mr-1" />
                        {revokingId === tok.id ? "Revoking..." : "Revoke"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
