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

      // Check for custom redirect or default to onboarding
      const redirectParam = searchParams.get("redirect");
      if (redirectParam && redirectParam.startsWith("/")) {
        router.push(redirectParam);
      } else {
        router.push("/onboarding");
      }
      router.refresh();
    } catch (err) {
      setError(formatAuthError(err));
      setStatus("idle");
    }
  };

  const isSubmitting = status === "submitting" || status === "success";

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#FBF7F0] px-6 py-20 [background:radial-gradient(1000px_600px_at_50%_-10%,#F6DCC2,transparent_70%)]">
      {/* Floating Top Glass Navigation matching Main.dc.html */}
      <header className="glass nav absolute top-6 left-1/2 -translate-x-1/2 w-[min(940px,92%)] flex items-center justify-between px-6 py-2.5 rounded-full z-30">
        <Link href="/" className="font-['Bricolage_Grotesque'] text-2xl font-bold tracking-tight text-[#2A170D] transition-transform hover:scale-105">
          Kova<span className="text-[#D58A56]">.</span>
        </Link>
        <div className="flex items-center gap-4 text-sm">
          <Link href="/" className="hidden sm:inline font-medium text-[#6B5646] hover:text-[#2A170D] transition-colors">
            ← Back to product
          </Link>
          <Link href={loginHref} className="btn !py-2 !px-4 !text-xs !font-semibold">
            Sign in
          </Link>
        </div>
      </header>

      {/* Ambient background orbs */}
      <div className="orb -left-20 top-20 h-[420px] w-[420px] bg-[#E9A878]" />
      <div className="orb -right-16 bottom-20 h-[380px] w-[380px] bg-[#C9733F] [animation-delay:-6s]" />

      {/* Floating Decorative Tiles flanking the card */}
      <div className="tile-float hidden lg:grid absolute left-12 xl:left-32 top-1/3 -rotate-12 pointer-events-none z-10">
        <svg width="28" height="28" viewBox="0 0 36 36" fill="#8A3513" stroke="#8A3513" strokeWidth="2" strokeLinejoin="round" aria-hidden="true">
          <path d="M8 5l22 10-9 3-3 9z" />
        </svg>
      </div>

      <div className="tile-float hidden lg:grid absolute right-12 xl:right-32 top-1/4 rotate-8 pointer-events-none z-10 [animation-delay:-3s]">
        <svg width="28" height="28" viewBox="0 0 16 16" fill="none" stroke="#3E9B5F" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M3 8.5l3 3 7-7" />
        </svg>
      </div>

      <div className="tile-float hidden xl:grid absolute left-24 bottom-24 rotate-6 pointer-events-none z-10 [animation-delay:-4.5s]">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="#D58A56" stroke="#8A3513" strokeWidth="1.5" strokeLinejoin="round" aria-hidden="true">
          <path d="M13 2L4 14h7l-1 8 9-12h-7z" />
        </svg>
      </div>

      {/* Main Glass Signup Card */}
      <div className="glass relative z-20 w-full max-w-[440px] p-8 sm:p-10 text-left animate-in fade-in zoom-in-95 duration-400">
        {/* Editorial Eyebrow & Header */}
        <div className="mb-8 text-center">
          <div className="inline-flex items-center gap-2 rounded-full border border-[#2A170D]/10 bg-white/80 px-3.5 py-1 text-xs font-medium text-[#2A170D] shadow-[0_4px_12px_-4px_rgba(90,40,10,0.15)] mb-4">
            <span className="h-2 w-2 rounded-full bg-[#3E9B5F] shadow-[0_0_0_4px_rgba(62,155,95,0.2)]" />
            <span>Autonomous software agent</span>
          </div>

          <h1 className="font-['Bricolage_Grotesque'] text-4xl sm:text-[42px] font-bold tracking-[-0.035em] text-[#2A170D] mb-2 leading-[1.05]">
            Create an <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">account.</em>
          </h1>
          <p className="text-[15px] text-[#6B5646] leading-relaxed">
            Start giving Kova goals and watch it work.
          </p>
        </div>

        {/* Form Container */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="name" className="block font-['DM_Mono'] text-xs font-medium uppercase tracking-[0.14em] text-[#8A3513]">
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
              className="h-12 rounded-xl border-[#2A170D]/15 bg-white font-sans text-sm text-[#2A170D] placeholder-[#6B5646]/50 shadow-[0_1px_3px_rgba(42,23,13,0.04)] focus:border-[#8A3513] focus:bg-white focus:ring-4 focus:ring-[#8A3513]/10 transition-all"
              required
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="email" className="block font-['DM_Mono'] text-xs font-medium uppercase tracking-[0.14em] text-[#8A3513]">
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
              className="h-12 rounded-xl border-[#2A170D]/15 bg-white font-sans text-sm text-[#2A170D] placeholder-[#6B5646]/50 shadow-[0_1px_3px_rgba(42,23,13,0.04)] focus:border-[#8A3513] focus:bg-white focus:ring-4 focus:ring-[#8A3513]/10 transition-all"
              required
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="password" className="block font-['DM_Mono'] text-xs font-medium uppercase tracking-[0.14em] text-[#8A3513]">
              Password
            </label>
            <PasswordInput
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 6 characters"
              autoComplete="new-password"
              disabled={isSubmitting}
              className="h-12 rounded-xl border-[#2A170D]/15 bg-white font-sans text-sm text-[#2A170D] placeholder-[#6B5646]/50 shadow-[0_1px_3px_rgba(42,23,13,0.04)] focus:border-[#8A3513] focus:bg-white focus:ring-4 focus:ring-[#8A3513]/10 transition-all"
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
            className="btn w-full !py-3.5 !text-[15px] !font-semibold mt-3 justify-center disabled:opacity-50 disabled:pointer-events-none cursor-pointer"
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
