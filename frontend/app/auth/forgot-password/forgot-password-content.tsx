"use client";

import { useState } from "react";
import Link from "next/link";
import { Logo } from "@/components/shared/logo";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createClient } from "@/lib/auth/client";
import { formatAuthError } from "@/lib/auth/errors";

export function ForgotPasswordContent() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [status, setStatus] = useState<"idle" | "submitting">("idle");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || status === "submitting") return;

    setStatus("submitting");
    setError(null);

    const cleanEmail = email.trim();

    try {
      const supabase = createClient();
      const { error: authError } = await supabase.auth.resetPasswordForEmail(cleanEmail, {
        redirectTo: `${window.location.origin}/auth/reset-password`,
      });

      if (authError) {
        setError(formatAuthError(authError));
        setStatus("idle");
        return;
      }

      setSent(true);
    } catch (err) {
      setError(formatAuthError(err));
      setStatus("idle");
    }
  };

  if (sent) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center px-6 py-12 bg-background select-none">
        <div className="w-full max-w-sm animate-in fade-in zoom-in-95 duration-300">
          <div className="mb-8 text-center">
            <Logo size="lg" className="mb-6 justify-center" />
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
              <MaterialIcon name="mail" size={24} className="text-primary" />
            </div>
            <h1 className="text-h2 font-semibold text-foreground mb-2">
              Check your email.
            </h1>
            <p className="text-body-sm text-muted-foreground">
              We sent a password reset link to{" "}
              <span className="font-medium text-foreground">{email}</span>.
            </p>
          </div>

          <p className="mt-6 text-center text-caption text-muted-foreground">
            Didn&apos;t receive it?{" "}
            <button
              onClick={() => {
                setSent(false);
                setEmail("");
              }}
              className="text-foreground font-medium underline underline-offset-4 hover:text-primary transition-colors"
            >
              Try again
            </button>
          </p>

          <p className="mt-3 text-center text-caption text-muted-foreground">
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

  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-6 py-12 bg-background select-none">
      <div className="w-full max-w-sm animate-in fade-in zoom-in-95 duration-300">
        {/* Editorial Header */}
        <div className="mb-8 text-center">
          <Logo size="lg" className="mb-6 justify-center" />
          <h1 className="text-h2 font-semibold text-foreground mb-2">
            Forgot your password?
          </h1>
          <p className="text-body-sm text-muted-foreground">
            Enter your email and we&apos;ll send you a reset link.
          </p>
        </div>

        {/* Form Container */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="email" className="text-caption font-medium text-foreground">
              Email
            </label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
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
            disabled={!email.trim() || status === "submitting"}
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
              "Send reset link"
            )}
          </Button>
        </form>

        {/* Footer Link */}
        <p className="mt-6 text-center text-caption text-muted-foreground">
          Remember your password?{" "}
          <Link
            href="/auth/login"
            className="text-foreground font-medium underline underline-offset-4 hover:text-primary transition-colors"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
