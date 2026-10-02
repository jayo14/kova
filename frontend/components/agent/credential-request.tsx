"use client";

import { useState } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { createCredential } from "@/lib/api/credentials";
import type { CredentialRequest } from "@/lib/types";

interface CredentialRequestProps {
  request: CredentialRequest;
  onSubmit: (email: string, password: string, save?: boolean) => void;
  error?: string | null;
  loading?: boolean;
  projectId?: string;
}

export function CredentialRequestForm({
  request,
  onSubmit,
  error,
  loading = false,
  projectId,
}: CredentialRequestProps) {
  const [isOpen, setIsOpen] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [saveCredential, setSaveCredential] = useState(false); // Strictly default unchecked

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanEmail = email.trim();
    const cleanPassword = password;

    if (!cleanEmail || !cleanPassword || loading) return;

    // Zero out password field immediately to minimize in-memory retention
    setPassword("");

    if (saveCredential) {
      try {
        await createCredential({
          name: cleanEmail.split("@")[0] ? `${cleanEmail.split("@")[0]} account` : "Test Account",
          email: cleanEmail,
          password: cleanPassword,
          projectId,
        });
      } catch {
        // Continue even if organization persistence fails — prioritize session execution
      }
    }

    onSubmit(cleanEmail, cleanPassword, saveCredential);
  };

  if (!isOpen) {
    return (
      <div className="w-full max-w-sm mx-auto text-center animate-in fade-in duration-200">
        <p className="text-body-sm text-muted-foreground mb-4">
          I can use a test account to continue exploring.
        </p>
        <Button onClick={() => setIsOpen(true)} size="lg" className="w-full">
          <MaterialIcon name="key" size={16} />
          Use a test account
        </Button>
      </div>
    );
  }

  return (
    <div className="w-full max-w-sm mx-auto animate-in fade-in zoom-in-95 duration-200">
      <div className="rounded-2xl border border-border bg-card p-6 shadow-sm">
        <div className="flex items-center gap-2 mb-2">
          <MaterialIcon name="lock" size={18} className="text-primary" />
          <h3 className="text-body font-semibold text-foreground">
            Test account
          </h3>
        </div>

        <p className="text-caption text-muted-foreground mb-5">
          This account is used only for Kova&apos;s isolated session.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-caption font-medium text-foreground">
              {request.emailLabel || "Email"}
            </label>
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="test-student@example.com"
              disabled={loading}
              autoComplete="username"
              required
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-caption font-medium text-foreground">
              {request.passwordLabel || "Password"}
            </label>
            <PasswordInput
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter account password"
              disabled={loading}
              autoComplete="current-password"
              required
            />
          </div>

          <label className="flex items-center gap-2.5 cursor-pointer py-1 select-none">
            <input
              type="checkbox"
              checked={saveCredential}
              onChange={(e) => setSaveCredential(e.target.checked)}
              disabled={loading}
              className="h-4 w-4 rounded border-input text-primary focus:ring-primary/20"
            />
            <span className="text-caption text-muted-foreground hover:text-foreground transition-colors">
              Save as a reusable test credential
            </span>
          </label>

          {error && (
            <div className="flex items-center gap-2 rounded-lg bg-destructive/5 border border-destructive/20 px-3 py-2">
              <MaterialIcon name="error" size={14} className="text-destructive shrink-0" />
              <p className="text-caption text-destructive">{error}</p>
            </div>
          )}

          <Button
            type="submit"
            disabled={!email.trim() || !password.trim() || loading}
            className="w-full font-medium"
            size="default"
          >
            {loading ? (
              <MaterialIcon name="progress_activity" size={16} className="animate-spin" />
            ) : (
              <>
                Continue
                <MaterialIcon name="arrow_forward" size={16} />
              </>
            )}
          </Button>
        </form>
      </div>
    </div>
  );
}
