"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Logo } from "@/components/shared/logo";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { PasswordInput } from "@/components/ui/password-input";
import { createClient } from "@/lib/auth/client";
import { formatAuthError } from "@/lib/auth/errors";

type Phase = "loading" | "form" | "success" | "error";

export function ResetPasswordContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [phase, setPhase] = useState<Phase>("loading");
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [status, setStatus] = useState<"idle" | "submitting">("idle");

  // Exchange the recovery code for a session on mount
  useEffect(() => {
    const code = searchParams.get("code");
    if (!code) {
      setPhase("error");
      setError("Invalid reset link. Please request a new one.");
      return;
    }

    const supabase = createClient();
    supabase.auth
      .exchangeCodeForSession(code)
      .then(({ error: authError }: any) => {
        if (authError) {
          setPhase("error");
          setError(formatAuthError(authError));
        } else {
          setPhase("form");
        }
      })
      .catch((err) => {
        setPhase("error");
        setError(formatAuthError(err));
      });
  }, [searchParams]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim() || status === "submitting") return;

    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setStatus("submitting");
    setError(null);

    const cleanPassword = password;
    setPassword("");
    setConfirmPassword("");

    try {
      const supabase = createClient();
      const { error: authError }: any = await supabase.auth.updateUser({
        password: cleanPassword,
      });

      if (authError) {
        setError(formatAuthError(authError));
        setStatus("idle");
        return;
      }

      setPhase("success");
    } catch (err: any) {
      setError(formatAuthError(err));
      setStatus("idle");
    }
  };

  // Loading state — exchanging code
  if (phase === "loading") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center px-6 py-12 bg-background">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 rounded-full border-2 border-primary/20 border-t-primary animate-spin" />
          <p className="text-body-sm text-muted-foreground">Verifying reset link...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (phase === "error") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center px-6 py-12 bg-background select-none">
        <div className="w-full max-w-sm animate-in fade-in zoom-in-95 duration-300">
          <div className="mb-8 text-center">
            <Logo size="lg" className="mb-6 justify-center" />
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
              <MaterialIcon name="error" size={24} className="text-destructive" />
            </div>
            <h1 className="text-h2 font-semibold text-foreground mb-2">
              Link expired.
            </h1>
            <p className="text-body-sm text-muted-foreground">
              {error || "This reset link is invalid or has expired."}
            </p>
          </div>

          <p className="mt-6 text-center text-caption text-muted-foreground">
            <Link
              href="/auth/forgot-password"
              className="text-foreground font-medium underline underline-offset-4 hover:text-primary transition-colors"
            >
              Request a new reset link
            </Link>
          </p>
        </div>
      </div>
    );
  }

  // Success state
  if (phase === "success") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center px-6 py-12 bg-background select-none">
        <div className="w-full max-w-sm animate-in fade-in zoom-in-95 duration-300">
          <div className="mb-8 text-center">
            <Logo size="lg" className="mb-6 justify-center" />
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-green-500/10">
              <MaterialIcon name="check_circle" size={24} className="text-green-600" />
            </div>
            <h1 className="text-h2 font-semibold text-foreground mb-2">
              Password updated.
            </h1>
            <p className="text-body-sm text-muted-foreground">
              Your password has been reset. You can now sign in.
            </p>
          </div>

          <Button
            onClick={() => router.push("/auth/login")}
            className="w-full font-medium"
            size="lg"
          >
            Sign in
            <MaterialIcon name="arrow_forward" size={18} />
          </Button>
        </div>
      </div>
    );
  }

  // Form state — enter new password
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-6 py-12 bg-background select-none">
      <div className="w-full max-w-sm animate-in fade-in zoom-in-95 duration-300">
        {/* Editorial Header */}
        <div className="mb-8 text-center">
          <Logo size="lg" className="mb-6 justify-center" />
          <h1 className="text-h2 font-semibold text-foreground mb-2">
            Set new password.
          </h1>
          <p className="text-body-sm text-muted-foreground">
            Choose a strong password for your account.
          </p>
        </div>

        {/* Form Container */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="password" className="text-caption font-medium text-foreground">
              New password
            </label>
            <PasswordInput
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 6 characters"
              autoComplete="new-password"
              disabled={status === "submitting"}
              required
              minLength={6}
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="confirmPassword" className="text-caption font-medium text-foreground">
              Confirm password
            </label>
            <PasswordInput
              id="confirmPassword"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Re-enter password"
              autoComplete="new-password"
              disabled={status === "submitting"}
              required
            />
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-xl bg-destructive/5 border border-destructive/20 px-3.5 py-2.5">
              <MaterialIcon
                name="error"
                size={16}
                className="shrink-0 text-destructive"
              />
              <p className="text-caption text-destructive leading-relaxed">{error}</p>
            </div>
          )}

          <Button
            type="submit"
            disabled={!password.trim() || !confirmPassword.trim() || status === "submitting"}
            className="w-full font-medium"
            size="lg"
          >
            {status === "submitting" ? (
              <MaterialIcon
                name="progress_activity"
                size={18}
                className="animate-spin"
              />
            ) : (
              "Update password"
            )}
          </Button>
        </form>

        {/* Footer Link */}
        <p className="mt-6 text-center text-caption text-muted-foreground">
          <Link
            href="/auth/login"
            className="text-foreground font-medium underline underline-offset-4 hover:text-primary transition-colors"
          >
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
