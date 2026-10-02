"use client";

import { useState } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";

export type AuthChoice = "create_account" | "manual_login";

export interface AuthChoiceDialogProps {
  hostname: string;
  reason?: string;
  onChoice: (choice: AuthChoice, details?: { email: string; password: string }) => void;
  error?: string | null;
  loading?: boolean;
  loadingMessage?: string;
}

export function AuthChoiceDialog({
  hostname,
  reason,
  onChoice,
  error,
  loading = false,
  loadingMessage,
}: AuthChoiceDialogProps) {
  const [selectedChoice, setSelectedChoice] = useState<AuthChoice | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [useCustomCredentials, setUseCustomCredentials] = useState(false);

  const handleCreateAccount = () => {
    if (useCustomCredentials && email.trim() && password) {
      onChoice("create_account", { email: email.trim(), password });
    } else {
      onChoice("create_account");
    }
  };

  const handleManualLogin = () => {
    onChoice("manual_login");
  };

  if (loading) {
    return (
      <div className="absolute inset-0 z-10 flex items-center justify-center animate-in fade-in duration-300">
        <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />
        <div className="relative w-full max-w-sm rounded-xl border border-border bg-card/95 p-6 shadow-lg backdrop-blur-sm">
          <div className="flex flex-col items-center text-center py-4">
            <div className="h-12 w-12 rounded-2xl border border-primary/20 bg-primary/5 flex items-center justify-center mb-4">
              <MaterialIcon name="progress_activity" size={24} className="text-primary animate-spin" />
            </div>
            <p className="text-body-sm font-medium text-foreground mb-1">
              {loadingMessage || "Creating account..."}
            </p>
            <p className="text-caption text-muted-foreground">
              Kova is setting up your test account on {hostname}
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (selectedChoice === "manual_login") {
    return (
      <ManualLoginForm
        hostname={hostname}
        reason={reason}
        error={error}
        onSubmit={(email, password) => onChoice("manual_login", { email, password })}
        onBack={() => setSelectedChoice(null)}
      />
    );
  }

  if (selectedChoice === "create_account") {
    return (
      <CreateAccountForm
        hostname={hostname}
        reason={reason}
        error={error}
        email={email}
        setEmail={setEmail}
        password={password}
        setPassword={setPassword}
        useCustomCredentials={useCustomCredentials}
        setUseCustomCredentials={setUseCustomCredentials}
        onSubmit={handleCreateAccount}
        onBack={() => setSelectedChoice(null)}
      />
    );
  }

  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center animate-in fade-in duration-300">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />
      <div className="relative w-full max-w-sm rounded-xl border border-border bg-card/95 p-6 shadow-lg backdrop-blur-sm">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <MaterialIcon name="lock" size={16} className="text-amber-600" />
            <span className="text-body-sm font-semibold text-foreground">
              Authentication Required
            </span>
          </div>
          <span className="rounded-full bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 text-[10px] text-amber-700 font-medium">
            Auth Gate
          </span>
        </div>

        <p className="text-caption text-muted-foreground mb-5">
          {reason && reason !== "Login" && reason !== "login"
            ? reason
            : `Kova needs access to continue exploring `}
          <span className="font-medium text-foreground">{hostname}</span>
        </p>

        {error && (
          <div className="flex items-start gap-2 rounded-lg bg-destructive/5 border border-destructive/20 px-3 py-2 mb-4">
            <MaterialIcon name="error" size={14} className="text-destructive shrink-0 mt-0.5" />
            <p className="text-caption text-destructive">{error}</p>
          </div>
        )}

        <div className="space-y-3">
          <button
            onClick={() => setSelectedChoice("create_account")}
            className="w-full flex items-center gap-3 rounded-xl border border-border bg-card/50 px-4 py-3.5 text-left transition-all hover:bg-card hover:border-primary/30 group"
          >
            <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 group-hover:bg-primary/15 transition-colors">
              <MaterialIcon name="person_add" size={20} className="text-primary" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-body-sm font-medium text-foreground">Create Account</p>
              <p className="text-caption text-muted-foreground">
                Kova will try to sign up automatically
              </p>
            </div>
            <MaterialIcon name="chevron_right" size={16} className="text-muted-foreground/40 shrink-0" />
          </button>

          <button
            onClick={() => setSelectedChoice("manual_login")}
            className="w-full flex items-center gap-3 rounded-xl border border-border bg-card/50 px-4 py-3.5 text-left transition-all hover:bg-card hover:border-primary/30 group"
          >
            <div className="h-10 w-10 rounded-lg bg-secondary flex items-center justify-center shrink-0 group-hover:bg-secondary/80 transition-colors">
              <MaterialIcon name="login" size={20} className="text-muted-foreground" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-body-sm font-medium text-foreground">Manual Login</p>
              <p className="text-caption text-muted-foreground">
                Enter your existing credentials
              </p>
            </div>
            <MaterialIcon name="chevron_right" size={16} className="text-muted-foreground/40 shrink-0" />
          </button>
        </div>

        <div className="mt-4 pt-3 border-t border-border/60 text-center">
          <p className="text-[11px] text-muted-foreground/60 font-mono">
            Credentials are stored securely for this project
          </p>
        </div>
      </div>
    </div>
  );
}

function CreateAccountForm({
  hostname,
  reason,
  error,
  email,
  setEmail,
  password,
  setPassword,
  useCustomCredentials,
  setUseCustomCredentials,
  onSubmit,
  onBack,
}: {
  hostname: string;
  reason?: string;
  error?: string | null;
  email: string;
  setEmail: (v: string) => void;
  password: string;
  setPassword: (v: string) => void;
  useCustomCredentials: boolean;
  setUseCustomCredentials: (v: boolean) => void;
  onSubmit: () => void;
  onBack: () => void;
}) {
  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center animate-in fade-in duration-300">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />
      <div className="relative w-full max-w-sm rounded-xl border border-border bg-card/95 p-6 shadow-lg backdrop-blur-sm">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <MaterialIcon name="person_add" size={16} className="text-primary" />
            <span className="text-body-sm font-semibold text-foreground">
              Create Account
            </span>
          </div>
          <button
            onClick={onBack}
            className="text-caption text-muted-foreground hover:text-foreground transition-colors"
          >
            Back
          </button>
        </div>

        <p className="text-caption text-muted-foreground mb-4">
          Kova will attempt to create a test account on <span className="font-medium text-foreground">{hostname}</span>.
          {reason && reason !== "Login" && reason !== "login" && (
            <span className="block mt-1 text-muted-foreground/80">{reason}</span>
          )}
        </p>

        {error && (
          <div className="flex items-start gap-2 rounded-lg bg-destructive/5 border border-destructive/20 px-3 py-2 mb-4">
            <MaterialIcon name="error" size={14} className="text-destructive shrink-0 mt-0.5" />
            <p className="text-caption text-destructive">{error}</p>
          </div>
        )}

        <div className="space-y-4">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={useCustomCredentials}
              onChange={(e) => setUseCustomCredentials(e.target.checked)}
              className="rounded border-border"
            />
            <span className="text-caption text-foreground">Use custom credentials</span>
          </label>

          {useCustomCredentials && (
            <div className="space-y-3 animate-in fade-in duration-200">
              <div className="space-y-1.5">
                <label className="text-caption font-medium text-foreground">Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="test-student@example.com"
                  autoComplete="username"
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-caption text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-caption font-medium text-foreground">Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter a password"
                  autoComplete="new-password"
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-caption text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                />
              </div>
            </div>
          )}

          {!useCustomCredentials && (
            <div className="rounded-lg bg-secondary/50 border border-border px-3 py-2.5">
              <p className="text-caption text-muted-foreground">
                <MaterialIcon name="auto_awesome" size={12} className="inline mr-1 text-primary" />
                Kova will generate a test email and password automatically
              </p>
            </div>
          )}

          <button
            onClick={onSubmit}
            className="w-full rounded-lg bg-primary px-3 py-2.5 text-caption font-medium text-primary-foreground hover:bg-primary/90 transition-colors flex items-center justify-center gap-2"
          >
            <MaterialIcon name="person_add" size={14} />
            Create Account
          </button>
        </div>
      </div>
    </div>
  );
}

function ManualLoginForm({
  hostname,
  reason,
  error,
  onSubmit,
  onBack,
}: {
  hostname: string;
  reason?: string;
  error?: string | null;
  onSubmit: (email: string, password: string) => void;
  onBack: () => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (email.trim() && password) {
      onSubmit(email.trim(), password);
    }
  };

  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center animate-in fade-in duration-300">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />
      <div className="relative w-full max-w-sm rounded-xl border border-border bg-card/95 p-6 shadow-lg backdrop-blur-sm">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <MaterialIcon name="login" size={16} className="text-muted-foreground" />
            <span className="text-body-sm font-semibold text-foreground">
              Manual Login
            </span>
          </div>
          <button
            onClick={onBack}
            className="text-caption text-muted-foreground hover:text-foreground transition-colors"
          >
            Back
          </button>
        </div>

        <p className="text-caption text-muted-foreground mb-4">
          Enter your credentials for <span className="font-medium text-foreground">{hostname}</span>
          {reason && reason !== "Login" && reason !== "login" && (
            <span className="block mt-1 text-muted-foreground/80">{reason}</span>
          )}
        </p>

        {error && (
          <div className="flex items-start gap-2 rounded-lg bg-destructive/5 border border-destructive/20 px-3 py-2 mb-4">
            <MaterialIcon name="error" size={14} className="text-destructive shrink-0 mt-0.5" />
            <p className="text-caption text-destructive">{error}</p>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1.5">
            <label className="text-caption font-medium text-foreground">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="test-student@example.com"
              autoComplete="username"
              required
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-caption text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-caption font-medium text-foreground">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter account password"
              autoComplete="current-password"
              required
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-caption text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
            />
          </div>
          <button
            type="submit"
            disabled={!email.trim() || !password}
            className="w-full rounded-lg bg-primary px-3 py-2.5 text-caption font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
          >
            <span>Continue</span>
            <MaterialIcon name="arrow_forward" size={14} />
          </button>
        </form>
      </div>
    </div>
  );
}
