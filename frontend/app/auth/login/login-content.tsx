"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Logo } from "@/components/shared/logo";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { createClient } from "@/lib/auth/client";
import { formatAuthError } from "@/lib/auth/errors";
import {
  savePendingIntent,
  getPendingIntent,
  clearPendingIntent,
  getPendingIntentFromParams,
  buildExploreDestination,
} from "@/lib/auth/pending-intent";
import { resolveUserOrganization } from "@/lib/auth/organization";

export function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "submitting" | "success">("idle");

  // Save pending intent if provided in URL parameters
  useEffect(() => {
    const fromParams = getPendingIntentFromParams(searchParams);
    if (fromParams) {
      savePendingIntent(fromParams);
    }
  }, [searchParams]);

  // Build query string for signup link to preserve intent and redirect
  const signupHref = (() => {
    const params = new URLSearchParams();
    const url = searchParams.get("url");
    const intent = searchParams.get("intent") || searchParams.get("workflow");
    const redirect = searchParams.get("redirect");

    if (url) params.set("url", url);
    if (intent) params.set("intent", intent);
    if (redirect) params.set("redirect", redirect);

    const qs = params.toString();
    return qs ? `/auth/signup?${qs}` : "/auth/signup";
  })();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password.trim() || status === "submitting") return;

    setStatus("submitting");
    setError(null);

    const cleanEmail = email.trim();
    const cleanPassword = password;
    // Clear password immediately from component state
    setPassword("");

    try {
      const supabase = createClient();
      const { data, error: authError } = await supabase.auth.signInWithPassword({
        email: cleanEmail,
        password: cleanPassword,
      });

      if (authError) {
        setError(formatAuthError(authError));
        setStatus("idle");
        return;
      }

      if (data.user) {
        resolveUserOrganization(data.user);
      }

      setStatus("success");

      // Check for pending exploration intent
      const pendingIntent = getPendingIntent() || getPendingIntentFromParams(searchParams);
      if (pendingIntent) {
        clearPendingIntent();
        router.push(buildExploreDestination(pendingIntent));
        return;
      }

      // Check for custom redirect or default to dashboard
      const redirectParam = searchParams.get("redirect");
      if (redirectParam && redirectParam.startsWith("/")) {
        router.push(redirectParam);
      } else {
        router.push("/dashboard");
      }
      router.refresh();
    } catch (err) {
      setError(formatAuthError(err));
      setStatus("idle");
    }
  };

  const isSubmitting = status === "submitting" || status === "success";

  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-6 py-12 bg-background select-none">
      <div className="w-full max-w-sm animate-in fade-in zoom-in-95 duration-300">
        {/* Editorial Header */}
        <div className="mb-8 text-center">
          <Logo size="lg" className="mb-6 justify-center" />
          <h1 className="text-h2 font-semibold text-foreground mb-2">
            Welcome back.
          </h1>
          <p className="text-body-sm text-muted-foreground">
            Sign in to your workspace.
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
              disabled={isSubmitting}
              required
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="password" className="text-caption font-medium text-foreground">
              Password
            </label>
            <PasswordInput
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
              autoComplete="current-password"
              disabled={isSubmitting}
              required
            />
            <div className="flex justify-end">
              <Link
                href="/auth/forgot-password"
                className="text-caption text-muted-foreground hover:text-primary transition-colors"
              >
                Forgot password?
              </Link>
            </div>
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
            disabled={!email.trim() || isSubmitting}
            className="w-full font-medium"
            size="lg"
          >
            {isSubmitting ? (
              <MaterialIcon
                name="progress_activity"
                size={18}
                className="animate-spin"
              />
            ) : (
              "Sign in"
            )}
          </Button>
        </form>

        {/* Footer Link */}
        <p className="mt-6 text-center text-caption text-muted-foreground">
          Don&apos;t have an account?{" "}
          <Link
            href={signupHref}
            className="text-foreground font-medium underline underline-offset-4 hover:text-primary transition-colors"
          >
            Create one
          </Link>
        </p>
      </div>
    </div>
  );
}
