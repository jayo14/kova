"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
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

export function SignupContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [name, setName] = useState("");
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

  // Build query string for login link to preserve intent and redirect
  const loginHref = (() => {
    const params = new URLSearchParams();
    const url = searchParams.get("url");
    const intent = searchParams.get("intent") || searchParams.get("workflow");
    const redirect = searchParams.get("redirect");

    if (url) params.set("url", url);
    if (intent) params.set("intent", intent);
    if (redirect) params.set("redirect", redirect);

    const qs = params.toString();
    return qs ? `/auth/login?${qs}` : "/auth/login";
  })();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !email.trim() || !password.trim() || status === "submitting") return;

    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }

    setStatus("submitting");
    setError(null);

    const cleanName = name.trim();
    const cleanEmail = email.trim();
    const cleanPassword = password;
    // Clear password immediately from component state
    setPassword("");

    try {
      const supabase = createClient();
      const { data, error: authError } = await supabase.auth.signUp({
        email: cleanEmail,
        password: cleanPassword,
        options: {
          data: { name: cleanName },
        },
      });

      if (authError) {
        setError(formatAuthError(authError));
        setStatus("idle");
        return;
      }

      if (data.user) {
        // Automatically provision workspace (e.g. John's Workspace)
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
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#FBF7F0] px-6 py-12 [background:radial-gradient(1000px_600px_at_50%_-10%,#F6DCC2,transparent_70%)]">
      {/* Ambient background orbs */}
      <div className="orb -left-20 top-20 h-[380px] w-[380px] bg-[#E9A878]" />
      <div className="orb -right-16 bottom-20 h-[340px] w-[340px] bg-[#C9733F] [animation-delay:-5s]" />

      <div className="relative z-10 w-full max-w-[420px] rounded-[32px] border border-white/80 bg-white/70 p-8 md:p-10 shadow-[0_1px_0_#fff_inset,0_30px_60px_-25px_rgba(90,40,10,0.22)] backdrop-blur-xl animate-in fade-in zoom-in-95 duration-300">
        {/* Editorial Header */}
        <div className="mb-8 text-center">
          <Link href="/" className="inline-flex items-center gap-1 font-['Bricolage_Grotesque'] text-3xl font-bold tracking-tight text-[#2A170D] transition-transform hover:scale-105 mb-5">
            Kova<span className="text-[#D58A56]">.</span>
          </Link>
          <h1 className="font-['Bricolage_Grotesque'] text-3xl md:text-4xl font-bold tracking-tight text-[#2A170D] mb-2">
            Create an <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">account.</em>
          </h1>
          <p className="text-sm text-[#6B5646]">
            Start giving Kova work to do.
          </p>
        </div>

        {/* Form Container */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="name" className="font-['DM_Mono'] text-xs font-medium uppercase tracking-wider text-[#6B5646]">
              Name
            </label>
            <Input
              id="name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Your name"
              autoComplete="name"
              disabled={isSubmitting}
              className="h-12 rounded-xl border-[#2A170D]/15 bg-white/80 font-sans text-sm text-[#2A170D] placeholder-[#6B5646]/50 shadow-sm focus:border-[#8A3513] focus:ring-2 focus:ring-[#8A3513]/15"
              required
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="email" className="font-['DM_Mono'] text-xs font-medium uppercase tracking-wider text-[#6B5646]">
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
              className="h-12 rounded-xl border-[#2A170D]/15 bg-white/80 font-sans text-sm text-[#2A170D] placeholder-[#6B5646]/50 shadow-sm focus:border-[#8A3513] focus:ring-2 focus:ring-[#8A3513]/15"
              required
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="password" className="font-['DM_Mono'] text-xs font-medium uppercase tracking-wider text-[#6B5646]">
              Password
            </label>
            <PasswordInput
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 6 characters"
              autoComplete="new-password"
              disabled={isSubmitting}
              className="h-12 rounded-xl border-[#2A170D]/15 bg-white/80 font-sans text-sm text-[#2A170D] placeholder-[#6B5646]/50 shadow-sm focus:border-[#8A3513] focus:ring-2 focus:ring-[#8A3513]/15"
              required
              minLength={6}
            />
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-xl bg-[#8A3513]/10 border border-[#8A3513]/20 px-3.5 py-2.5">
              <MaterialIcon
                name="error"
                size={16}
                className="shrink-0 text-[#8A3513]"
              />
              <p className="text-xs text-[#8A3513] leading-relaxed">{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={!name.trim() || !email.trim() || isSubmitting}
            className="btn-pill w-full !py-3.5 !text-sm mt-2 disabled:opacity-50 disabled:pointer-events-none"
          >
            {isSubmitting ? (
              <MaterialIcon
                name="progress_activity"
                size={18}
                className="animate-spin"
              />
            ) : (
              "Create account →"
            )}
          </button>
        </form>

        {/* Footer Link */}
        <p className="mt-8 text-center text-xs text-[#6B5646]">
          Already have an account?{" "}
          <Link
            href={loginHref}
            className="font-semibold text-[#8A3513] underline underline-offset-4 hover:text-[#6e2a10] transition-colors"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
