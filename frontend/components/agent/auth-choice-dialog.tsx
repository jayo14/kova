"use client";

import { useEffect, useState } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";
import type { Credential } from "@/lib/types";
import { getExplorationCredentials } from "@/lib/api/exploration";
import { getCredentials } from "@/lib/api/credentials";

export type AuthChoice = "create_account" | "manual_login" | "use_existing";

export interface AuthChoiceDialogProps {
  hostname: string;
  reason?: string;
  projectId?: string | null;
  sessionId?: string | null;
  onChoice: (
    choice: AuthChoice,
    details?: { email?: string; password?: string; credentialId?: string }
  ) => void;
  error?: string | null;
  loading?: boolean;
  loadingMessage?: string;
}

export function AuthChoiceDialog({
  hostname,
  reason,
  projectId,
  sessionId,
  onChoice,
  error,
  loading = false,
  loadingMessage,
}: AuthChoiceDialogProps) {
  const [storedCredentials, setStoredCredentials] = useState<Credential[]>([]);
  const [loadingStoredCredentials, setLoadingStoredCredentials] = useState(false);
  const [selectedCredId, setSelectedCredId] = useState<string>("");
  const [activeTab, setActiveTab] = useState<"smart" | "manual">("smart");
  const [isPeeking, setIsPeeking] = useState(false);

  // Manual login fields
  const [manualEmail, setManualEmail] = useState("");
  const [manualPassword, setManualPassword] = useState("");

  // Load existing credentials for this session, project, or hostname
  useEffect(() => {
    let cancelled = false;

    async function loadStored() {
      setLoadingStoredCredentials(true);
      try {
        let creds: Credential[] = [];

        // 1. Try exploration session credentials
        if (sessionId) {
          try {
            creds = await getExplorationCredentials(sessionId);
          } catch {
            // fallback
          }
        }

        // 2. Try project-scoped credentials
        if (creds.length === 0 && projectId) {
          try {
            creds = await getCredentials(projectId);
          } catch {
            // fallback
          }
        }

        // 3. Match user credentials by hostname stem or project
        if (creds.length === 0) {
          try {
            const all = await getCredentials();
            const hostNorm = hostname.toLowerCase().replace(/^(?:https?:\/\/)?(?:www\d*\.)?/, "").split("/")[0].split(":")[0];
            const hostStem = hostNorm.split(".")[0];

            const matched = all.filter((c) => {
              if (projectId && c.projectId === projectId) return true;
              const pName = (c.projectName || "").toLowerCase();
              if (pName && hostStem && (pName.includes(hostStem) || hostStem.includes(pName))) return true;
              if (pName && hostNorm && (pName.includes(hostNorm) || hostNorm.includes(pName))) return true;
              return false;
            });
            creds = matched.length > 0 ? matched : all;
          } catch {
            // ignore
          }
        }

        if (!cancelled) {
          setStoredCredentials(creds);
          if (creds.length > 0) {
            setSelectedCredId(creds[0].id);
          }
        }
      } finally {
        if (!cancelled) {
          setLoadingStoredCredentials(false);
        }
      }
    }

    loadStored();

    return () => {
      cancelled = true;
    };
  }, [sessionId, projectId, hostname]);

  const handleUseStored = (credId?: string) => {
    const idToUse = credId || selectedCredId || storedCredentials[0]?.id;
    const cred = storedCredentials.find((c) => c.id === idToUse);
    if (idToUse) {
      onChoice("use_existing", { credentialId: idToUse, email: cred?.email });
    }
  };

  const handleAutoCreate = () => {
    onChoice("create_account");
  };

  const handleManualSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualEmail.trim() || !manualPassword) return;
    onChoice("manual_login", {
      email: manualEmail.trim(),
      password: manualPassword,
    });
  };

  // If user wants to peek at the underlying webpage
  if (isPeeking) {
    return (
      <div className="absolute top-4 right-4 z-20 animate-in fade-in duration-200">
        <button
          onClick={() => setIsPeeking(false)}
          className="flex items-center gap-2 rounded-xl border border-primary/40 bg-card/95 px-4 py-2.5 shadow-xl backdrop-blur-md hover:bg-card hover:border-primary transition-all text-caption font-medium text-foreground cursor-pointer"
        >
          <MaterialIcon name="lock" size={16} className="text-amber-500" />
          <span>Return to Authentication Card</span>
          <MaterialIcon name="visibility_off" size={16} className="text-muted-foreground ml-1" />
        </button>
      </div>
    );
  }

  // Loading state
  if (loading) {
    return (
      <div className="absolute inset-0 z-10 flex items-center justify-center animate-in fade-in duration-300">
        <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />
        <div className="relative w-full max-w-sm rounded-2xl border border-border/80 bg-card/95 p-6 shadow-2xl backdrop-blur-md">
          <div className="flex flex-col items-center text-center py-4">
            <div className="h-12 w-12 rounded-2xl border border-primary/20 bg-primary/10 flex items-center justify-center mb-4">
              <MaterialIcon name="progress_activity" size={24} className="text-primary animate-spin" />
            </div>
            <p className="text-body-sm font-semibold text-foreground mb-1">
              {loadingMessage || "Authenticating..."}
            </p>
            <p className="text-caption text-muted-foreground">
              Kova is configuring your session on <span className="font-medium text-foreground">{hostname}</span>
            </p>
          </div>
        </div>
      </div>
    );
  }

  const hasStoredCredentials = storedCredentials.length > 0;
  const activeCred = storedCredentials.find((c) => c.id === selectedCredId) || storedCredentials[0];

  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center p-4 animate-in fade-in duration-200">
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-[2px] transition-opacity cursor-pointer"
        onClick={() => setIsPeeking(true)}
        title="Click to peek behind the card"
      />

      <div className="relative w-full max-w-md rounded-2xl border border-border/80 bg-card/98 p-6 shadow-2xl backdrop-blur-md space-y-5">
        {/* Header with Peek Button */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center">
              <MaterialIcon name="lock" size={18} className="text-amber-500" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-body-sm font-semibold text-foreground">
                  Authentication Required
                </span>
                <span className="rounded-full bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 text-[10px] text-amber-600 font-medium">
                  Protected View
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground">
                Target: <span className="font-medium text-foreground">{hostname}</span>
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => setIsPeeking(true)}
            className="flex items-center gap-1 rounded-lg px-2.5 py-1 text-[11px] text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors cursor-pointer"
            title="Inspect page behind this dialog"
          >
            <MaterialIcon name="visibility" size={14} />
            <span>Peek</span>
          </button>
        </div>

        {/* Reason banner if present */}
        {reason && reason.toLowerCase() !== "login" && (
          <p className="text-caption text-muted-foreground/90 bg-secondary/40 border border-border/60 rounded-xl px-3.5 py-2">
            {reason}
          </p>
        )}

        {/* Error alert */}
        {error && (
          <div className="flex items-start gap-2.5 rounded-xl bg-destructive/10 border border-destructive/20 p-3 text-caption text-destructive">
            <MaterialIcon name="error" size={16} className="shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="font-medium">Authentication couldn&apos;t be completed</p>
              <p className="text-[11px] opacity-90 mt-0.5">{error}</p>
            </div>
          </div>
        )}

        {/* Mode Selector Tabs (Smart Auto vs Manual) */}
        <div className="flex rounded-xl bg-secondary/60 p-1 border border-border/60">
          <button
            type="button"
            onClick={() => setActiveTab("smart")}
            className={cn(
              "flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-caption font-medium transition-all cursor-pointer",
              activeTab === "smart"
                ? "bg-card text-foreground shadow-xs border border-border/40 font-semibold"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <MaterialIcon name={hasStoredCredentials ? "key" : "bolt"} size={14} className={hasStoredCredentials ? "text-primary" : "text-amber-500"} />
            <span>{hasStoredCredentials ? "Saved Account" : "1-Click Auto"}</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("manual")}
            className={cn(
              "flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-caption font-medium transition-all cursor-pointer",
              activeTab === "manual"
                ? "bg-card text-foreground shadow-xs border border-border/40 font-semibold"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <MaterialIcon name="edit" size={14} />
            <span>Enter Credentials</span>
          </button>
        </div>

        {/* Tab 1: Smart / Frictionless Path */}
        {activeTab === "smart" && (
          <div className="space-y-4">
            {hasStoredCredentials ? (
              /* Case A: Saved credentials exist */
              <div className="space-y-3">
                <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-primary">
                      Ready to use
                    </span>
                    <span className="rounded-full bg-primary/20 px-2 py-0.5 text-[10px] text-primary font-medium">
                      {storedCredentials.length} saved
                    </span>
                  </div>

                  {storedCredentials.length === 1 ? (
                    <div className="flex items-center gap-3">
                      <div className="h-10 w-10 rounded-xl bg-primary/15 border border-primary/20 flex items-center justify-center shrink-0">
                        <MaterialIcon name="key" size={20} className="text-primary" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-body-sm font-semibold text-foreground truncate">
                          {activeCred.email}
                        </p>
                        <p className="text-[11px] text-muted-foreground truncate">
                          {activeCred.name || "Saved test account"}
                        </p>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <select
                        value={selectedCredId}
                        onChange={(e) => setSelectedCredId(e.target.value)}
                        className="w-full rounded-xl border border-border bg-background px-3 py-2 text-caption text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
                      >
                        {storedCredentials.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.email} ({c.name || "Saved credential"})
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={() => handleUseStored(selectedCredId)}
                    className="w-full rounded-xl bg-primary px-4 py-3 text-caption font-semibold text-primary-foreground hover:bg-primary/90 transition-all flex items-center justify-center gap-2 shadow-sm cursor-pointer"
                  >
                    <span>Continue as {activeCred?.email?.split("@")[0] || "Test User"}</span>
                    <MaterialIcon name="arrow_forward" size={16} />
                  </button>
                </div>

                {/* Subtle secondary option to auto-create instead */}
                <div className="text-center pt-1">
                  <button
                    type="button"
                    onClick={handleAutoCreate}
                    className="text-[12px] text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1 cursor-pointer"
                  >
                    <MaterialIcon name="add" size={14} />
                    <span>Or auto-create a new disposable test account instead</span>
                  </button>
                </div>
              </div>
            ) : (
              /* Case B: No saved credentials -> 1-Click Auto Pilot */
              <div className="space-y-3">
                <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <div className="h-9 w-9 rounded-xl bg-primary/15 border border-primary/20 flex items-center justify-center shrink-0">
                      <MaterialIcon name="auto_awesome" size={20} className="text-primary" />
                    </div>
                    <div>
                      <p className="text-body-sm font-semibold text-foreground">
                        Auto-Create Test Account
                      </p>
                      <p className="text-[11px] text-muted-foreground">
                        Zero setup required &mdash; Kova handles sign up automatically.
                      </p>
                    </div>
                  </div>

                  <p className="text-[11px] text-muted-foreground leading-relaxed">
                    Kova will generate a secure disposable test account, fill in the registration form, and proceed to map protected journeys.
                  </p>

                  <button
                    type="button"
                    onClick={handleAutoCreate}
                    className="w-full rounded-xl bg-primary px-4 py-3 text-caption font-semibold text-primary-foreground hover:bg-primary/90 transition-all flex items-center justify-center gap-2 shadow-sm cursor-pointer"
                  >
                    <MaterialIcon name="bolt" size={16} />
                    <span>Auto-Create &amp; Continue</span>
                    <MaterialIcon name="arrow_forward" size={16} />
                  </button>
                </div>

                <div className="text-center pt-1">
                  <p className="text-[11px] text-muted-foreground/70">
                    Created test credentials are saved automatically for future runs.
                  </p>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tab 2: Manual Login with Custom Credentials */}
        {activeTab === "manual" && (
          <form onSubmit={handleManualSubmit} className="space-y-3">
            <div className="space-y-1">
              <label className="text-[11px] font-medium text-foreground">
                Email or Username
              </label>
              <input
                type="text"
                value={manualEmail}
                onChange={(e) => setManualEmail(e.target.value)}
                placeholder="test-account@example.com"
                autoComplete="username"
                required
                className="w-full rounded-xl border border-border bg-background px-3 py-2 text-caption text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
              />
            </div>

            <div className="space-y-1">
              <label className="text-[11px] font-medium text-foreground">
                Password
              </label>
              <input
                type="password"
                value={manualPassword}
                onChange={(e) => setManualPassword(e.target.value)}
                placeholder="Enter password"
                autoComplete="current-password"
                required
                className="w-full rounded-xl border border-border bg-background px-3 py-2 text-caption text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
              />
            </div>

            <button
              type="submit"
              disabled={!manualEmail.trim() || !manualPassword}
              className="w-full rounded-xl bg-primary px-4 py-2.5 text-caption font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2 shadow-xs cursor-pointer mt-2"
            >
              <span>Sign In &amp; Continue</span>
              <MaterialIcon name="arrow_forward" size={16} />
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
