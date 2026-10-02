"use client";

import { useState } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import type { ExploreState, CredentialRequest } from "@/lib/types";
import type { ScreenshotEntry } from "@/components/explore/explore-state-machine";
import type { AuthMode } from "@/components/explore/explore-state-machine";
import type { AuthChoice } from "@/components/agent/auth-choice-dialog";
import { AuthChoiceDialog } from "@/components/agent/auth-choice-dialog";
import { cn } from "@/lib/utils";

export interface AgentBrowserViewportProps {
  url: string;
  state?: ExploreState;
  currentPath?: string;
  latestScreenshot?: string | null;
  screenshots?: ScreenshotEntry[];
  showScreenshotOverlay?: boolean;
  cursorPosition?: { x: number; y: number } | null;
  isActive?: boolean;
  credentialRequest?: CredentialRequest | null;
  authMode?: AuthMode;
  onCredentialSubmit?: (email: string, password: string, save?: boolean) => void;
  onAuthChoice?: (choice: AuthChoice, details?: { email: string; password: string }) => void;
  credentialError?: string | null;
  credentialLoading?: boolean;
  onUrlChange?: (url: string, path: string) => void;
  onThumbnailClick?: (index: number) => void;
  className?: string;
}

/**
 * Exploration browser viewer.
 *
 * IMPORTANT: this is NOT the browser Kova controls. It renders the real
 * Playwright browser's screenshots (server-side truth) plus the real URL/title
 * reported by the browser session. The prior implementation embedded the target
 * site in a client-side <iframe>, which (a) is not the Kova-controlled browser
 * and (b) breaks under X-Frame-Options/CSP on most real applications.
 */
export function AgentBrowserViewport({
  url,
  state = "exploring",
  currentPath,
  latestScreenshot,
  screenshots = [],
  showScreenshotOverlay = false,
  isActive = false,
  credentialRequest,
  authMode = "choice",
  onCredentialSubmit,
  onAuthChoice,
  credentialError,
  credentialLoading,
  onThumbnailClick,
  className,
}: AgentBrowserViewportProps) {
  const [isSnapshotExpanded, setIsSnapshotExpanded] = useState(false);

  const hostname = (() => {
    try {
      return new URL(url).hostname;
    } catch {
      return url.replace(/^https?:\/\//, "").split("/")[0] || "product.com";
    }
  })();

  const recentScreenshots = screenshots.slice(-3).reverse();

  const showConnectingOverlay = state === "connecting";
  const showAuthOverlay = state === "auth_required" || state === "authenticating";

  return (
    <div
      className={cn(
        "flex flex-col rounded-2xl border border-border bg-card shadow-sm overflow-hidden transition-all duration-300",
        className
      )}
    >
      {/* ── Browser Chrome ─────────────────────────────────────── */}
      <div className="flex items-center justify-between border-b border-border bg-secondary/30 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5" aria-hidden="true">
            <span className="h-2.5 w-2.5 rounded-full bg-border" />
            <span className="h-2.5 w-2.5 rounded-full bg-border" />
            <span className="h-2.5 w-2.5 rounded-full bg-border" />
          </div>
        </div>

        {/* Address Bar — real URL reported by the Kova browser session */}
        <div className="flex flex-1 max-w-md items-center justify-center mx-3">
          <div className="flex w-full items-center gap-2 rounded-lg border border-border/80 bg-background/90 px-3 py-1 text-caption text-foreground">
            <MaterialIcon name="lock" size={12} className="text-emerald-600 shrink-0" />
            <span className="font-mono font-medium truncate">
              {hostname}
              <span className="text-muted-foreground">{currentPath || "/"}</span>
            </span>
          </div>
        </div>

        {/* Status Pill + Screenshot Count */}
        <div className="flex items-center gap-2">
          {screenshots.length > 0 && (
            <button
              onClick={() => onThumbnailClick?.(screenshots.length - 1)}
              className="hidden sm:inline-flex items-center gap-1 rounded-md bg-secondary/60 px-2 py-0.5 text-[11px] font-mono text-muted-foreground hover:bg-secondary transition-colors cursor-pointer"
              title="View all screenshots"
            >
              <MaterialIcon name="photo_library" size={12} />
              {screenshots.length}
            </button>
          )}
          <span className="hidden sm:inline-flex items-center gap-1 rounded-md bg-primary/10 border border-primary/20 px-2 py-0.5 text-[11px] font-mono text-primary">
            <span className={cn("h-1.5 w-1.5 rounded-full", isActive ? "bg-primary animate-pulse" : "bg-muted-foreground/40")} />
            Playwright session
          </span>
        </div>
      </div>

      {/* ── Viewport: real Playwright screenshots ───────────────── */}
      <div className="relative flex-1 min-h-[380px] md:min-h-[460px] bg-background/50 overflow-hidden select-none">

        {latestScreenshot ? (
          /* Latest real browser screenshot, click to expand */
          <div
            className="absolute inset-0 flex flex-col items-center justify-center p-4 cursor-zoom-in"
            onClick={() => setIsSnapshotExpanded(true)}
            title="Click to expand the browser snapshot"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              key={latestScreenshot}
              src={latestScreenshot}
              alt={`Kova browser view of ${hostname}`}
              className="max-h-full max-w-full w-auto h-auto rounded-lg border border-border/80 object-contain shadow-md bg-background animate-in fade-in duration-300"
            />
            <div className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-secondary/70 px-3 py-1 text-[11px] font-mono text-muted-foreground">
              <MaterialIcon name="verified" size={12} className="text-emerald-600" />
              Kova browser (real Playwright view)
            </div>
          </div>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center p-6">
            <div className="flex flex-col items-center text-center">
              <div className="h-12 w-12 rounded-2xl border border-primary/20 bg-primary/5 flex items-center justify-center mb-4">
                <MaterialIcon name="sync" size={24} className={cn("text-primary", isActive && "animate-spin")} />
              </div>
              <p className="text-body font-medium text-foreground mb-1">
                {showConnectingOverlay ? `Connecting to ${hostname}` : "Waiting for browser view"}
              </p>
              <p className="text-caption text-muted-foreground max-w-xs">
                Screenshots of the isolated Kova browser session will appear here as it explores.
              </p>
            </div>
          </div>
        )}

        {/* Expanded snapshot overlay */}
        {latestScreenshot && isSnapshotExpanded && (
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center p-4 bg-background/95 backdrop-blur-xs animate-in fade-in duration-200">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={latestScreenshot}
              alt="Kova browser snapshot"
              className="max-h-[85%] w-auto max-w-full rounded-xl border border-border/80 object-contain shadow-md bg-background"
            />
            <div className="mt-3 flex items-center gap-3">
              <div className="inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-secondary/70 px-3 py-1 text-caption font-mono text-foreground">
                <MaterialIcon name="verified" size={13} className="text-emerald-600" />
                Kova browser snapshot
              </div>
              <button
                onClick={() => setIsSnapshotExpanded(false)}
                className="inline-flex items-center gap-1 text-caption text-primary hover:underline cursor-pointer"
                type="button"
              >
                <span>Back to browser view</span>
                <MaterialIcon name="close" size={13} />
              </button>
            </div>
          </div>
        )}

        {/* Auth gate overlay */}
        {showAuthOverlay && authMode !== "manual_login" && (
          <AuthChoiceDialog
            hostname={hostname}
            reason={credentialRequest?.reason}
            onChoice={onAuthChoice ? (choice, details) => onAuthChoice(choice, details) : () => {}}
            error={credentialError}
            loading={credentialLoading && authMode === "creating_account"}
            loadingMessage={authMode === "creating_account" ? "Creating account..." : undefined}
          />
        )}

        {showAuthOverlay && authMode === "manual_login" && (
          <ManualLoginOverlay
            hostname={hostname}
            credentialRequest={credentialRequest}
            credentialError={credentialError}
            state={state}
            onAuthChoice={onAuthChoice}
            onCredentialSubmit={onCredentialSubmit}
            credentialLoading={credentialLoading}
          />
        )}
      </div>

      {/* ── Thumbnail Strip — bottom of viewport ─────────────── */}
      {recentScreenshots.length > 0 && (
        <div className="flex items-center gap-2 border-t border-border bg-secondary/20 px-3 py-2">
          <span className="text-[10px] font-mono text-muted-foreground/80 shrink-0">snapshots</span>
          <div className="flex gap-1.5 overflow-x-auto">
            {recentScreenshots.map((s, i) => {
              const realIndex = screenshots.length - 1 - i;
              return (
                <button
                  key={s.id}
                  onClick={() => onThumbnailClick?.(realIndex)}
                  className="shrink-0 w-14 h-10 rounded-md overflow-hidden border border-border hover:border-primary/50 transition-colors opacity-80 hover:opacity-100"
                  title={s.label || `Screenshot ${realIndex + 1}`}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={s.url}
                    alt={`Snapshot ${realIndex + 1}`}
                    className="w-full h-full object-cover"
                  />
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function ManualLoginOverlay({
  hostname,
  credentialRequest,
  credentialError,
  state,
  onAuthChoice,
  onCredentialSubmit,
  credentialLoading,
}: {
  hostname: string;
  credentialRequest?: CredentialRequest | null;
  credentialError?: string | null;
  state: ExploreState;
  onAuthChoice?: (choice: AuthChoice, details?: { email: string; password: string }) => void;
  onCredentialSubmit?: (email: string, password: string, save?: boolean) => void;
  credentialLoading?: boolean;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!onCredentialSubmit || !email.trim() || !password || credentialLoading) return;
    onCredentialSubmit(email.trim(), password);
    setEmail("");
    setPassword("");
  };

  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center animate-in fade-in duration-300">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />
      <div className="relative w-full max-w-sm rounded-xl border border-border bg-card/95 p-6 shadow-lg backdrop-blur-sm">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <MaterialIcon name="lock" size={16} className="text-amber-600" />
            <span className="text-body-sm font-semibold text-foreground">
              {credentialError ? "Authentication Failed" : "Manual Login"}
            </span>
          </div>
          <button
            onClick={() => onAuthChoice ? onAuthChoice("manual_login") : undefined}
            className="text-caption text-muted-foreground hover:text-foreground transition-colors"
          >
            Back
          </button>
        </div>

        {credentialError ? (
          <div className="flex items-start gap-2 rounded-lg bg-destructive/5 border border-destructive/20 px-3 py-2 mb-4">
            <MaterialIcon name="error" size={14} className="text-destructive shrink-0 mt-0.5" />
            <div>
              <p className="text-caption text-destructive font-medium">{credentialError}</p>
              <p className="text-[11px] text-muted-foreground mt-1">Please enter correct credentials to continue.</p>
            </div>
          </div>
        ) : (
          <p className="text-caption text-muted-foreground mb-4">
            {credentialRequest?.reason && credentialRequest.reason !== "Login" && credentialRequest.reason !== "login"
              ? credentialRequest.reason
              : `Kova needs a test account to continue exploring `}
            {!credentialError && <span className="font-medium text-foreground">{hostname}</span>}
          </p>
        )}

        {state === "authenticating" ? (
          <div className="rounded-lg bg-secondary/50 border border-border px-3 py-2 text-caption text-muted-foreground">
            <span className="flex items-center gap-2">
              <MaterialIcon name="progress_activity" size={14} className="animate-spin text-primary" />
              Signing in with test credentials...
            </span>
          </div>
        ) : onCredentialSubmit ? (
          <form onSubmit={handleSubmit} className="space-y-3">
            <div className="space-y-1.5">
              <label className="text-caption font-medium text-foreground">
                {credentialRequest?.emailLabel || "Email"}
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="test-student@example.com"
                disabled={credentialLoading}
                autoComplete="username"
                required
                className="w-full rounded-lg border border-border bg-background px-3 py-2 text-caption text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-caption font-medium text-foreground">
                {credentialRequest?.passwordLabel || "Password"}
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter account password"
                disabled={credentialLoading}
                autoComplete="current-password"
                required
                className="w-full rounded-lg border border-border bg-background px-3 py-2 text-caption text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
              />
            </div>
            {credentialError && (
              <div className="flex items-center gap-2 rounded-lg bg-destructive/5 border border-destructive/20 px-3 py-2">
                <MaterialIcon name="error" size={14} className="text-destructive shrink-0 mt-0.5" />
                <p className="text-caption text-destructive">{credentialError}</p>
              </div>
            )}
            <button
              type="submit"
              disabled={!email.trim() || !password || credentialLoading}
              className="w-full rounded-lg bg-primary px-3 py-2 text-caption font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {credentialLoading ? (
                <span className="flex items-center justify-center gap-2">
                  <MaterialIcon name="progress_activity" size={14} className="animate-spin" />
                  Signing in...
                </span>
              ) : (
                <span className="flex items-center justify-center gap-2">
                  Continue
                  <MaterialIcon name="arrow_forward" size={14} />
                </span>
              )}
            </button>
          </form>
        ) : (
          <div className="rounded-lg bg-secondary/50 border border-border px-3 py-2 text-caption text-muted-foreground">
            Waiting for credential input...
          </div>
        )}
      </div>
    </div>
  );
}
