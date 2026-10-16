"use client";

import { useState } from "react";
import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
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
      <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#FBF7F0] px-6 py-20 [background:radial-gradient(1000px_600px_at_50%_-10%,#F6DCC2,transparent_70%)]">
        {/* Floating Top Glass Navigation */}
        <header className="glass nav absolute top-6 left-1/2 -translate-x-1/2 w-[min(940px,92%)] flex items-center justify-between px-6 py-2.5 rounded-full z-30">
          <Link href="/" className="font-['Bricolage_Grotesque'] text-2xl font-bold tracking-tight text-[#2A170D] transition-transform hover:scale-105">
            Kova<span className="text-[#D58A56]">.</span>
          </Link>
          <div className="flex items-center gap-4 text-sm">
            <Link href="/auth/login" className="btn !py-2 !px-4 !text-xs !font-semibold">
              Sign in
            </Link>
          </div>
        </header>

        {/* Ambient background orbs */}
        <div className="orb -left-20 top-20 h-[420px] w-[420px] bg-[#E9A878]" />
        <div className="orb -right-16 bottom-20 h-[380px] w-[380px] bg-[#C9733F] [animation-delay:-6s]" />

        {/* Main Glass Card */}
        <div className="glass relative z-20 w-full max-w-[440px] p-8 sm:p-10 text-left animate-in fade-in zoom-in-95 duration-400">
          <div className="mb-8 text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#8A3513]/10 border border-[#8A3513]/20 text-[#8A3513]">
              <MaterialIcon name="mail" size={26} />
            </div>
            <h1 className="font-['Bricolage_Grotesque'] text-4xl sm:text-[42px] font-bold tracking-[-0.035em] text-[#2A170D] mb-2 leading-[1.05]">
              Check your <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">email.</em>
            </h1>
            <p className="text-[15px] text-[#6B5646] leading-relaxed">
              We sent a password reset link to{" "}
              <span className="font-semibold text-[#2A170D]">{email}</span>.
            </p>
          </div>

          <p className="mt-6 text-center text-xs text-[#6B5646]">
            Didn&apos;t receive it?{" "}
            <button
              onClick={() => {
                setSent(false);
                setEmail("");
              }}
              className="font-semibold text-[#8A3513] underline underline-offset-4 hover:text-[#6e2a10] transition-colors cursor-pointer"
            >
              Try again
            </button>
          </p>

          <p className="mt-4 text-center text-xs text-[#6B5646]">
            <Link
              href="/auth/login"
              className="font-semibold text-[#8A3513] underline underline-offset-4 hover:text-[#6e2a10] transition-colors"
            >
              Back to sign in
            </Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#FBF7F0] px-6 py-20 [background:radial-gradient(1000px_600px_at_50%_-10%,#F6DCC2,transparent_70%)]">
      {/* Floating Top Glass Navigation */}
      <header className="glass nav absolute top-6 left-1/2 -translate-x-1/2 w-[min(940px,92%)] flex items-center justify-between px-6 py-2.5 rounded-full z-30">
        <Link href="/" className="font-['Bricolage_Grotesque'] text-2xl font-bold tracking-tight text-[#2A170D] transition-transform hover:scale-105">
          Kova<span className="text-[#D58A56]">.</span>
        </Link>
        <div className="flex items-center gap-4 text-sm">
          <Link href="/" className="hidden sm:inline font-medium text-[#6B5646] hover:text-[#2A170D] transition-colors">
            ← Back to product
          </Link>
          <Link href="/auth/login" className="btn !py-2 !px-4 !text-xs !font-semibold">
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

      {/* Main Glass Reset Card */}
      <div className="glass relative z-20 w-full max-w-[440px] p-8 sm:p-10 text-left animate-in fade-in zoom-in-95 duration-400">
        {/* Editorial Eyebrow & Header */}
        <div className="mb-8 text-center">
          <div className="inline-flex items-center gap-2 rounded-full border border-[#2A170D]/10 bg-white/80 px-3.5 py-1 text-xs font-medium text-[#2A170D] shadow-[0_4px_12px_-4px_rgba(90,40,10,0.15)] mb-4">
            <span className="h-2 w-2 rounded-full bg-[#3E9B5F] shadow-[0_0_0_4px_rgba(62,155,95,0.2)]" />
            <span>Account recovery</span>
          </div>

          <h1 className="font-['Bricolage_Grotesque'] text-4xl sm:text-[42px] font-bold tracking-[-0.035em] text-[#2A170D] mb-2 leading-[1.05]">
            Forgot <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">password?</em>
          </h1>
          <p className="text-[15px] text-[#6B5646] leading-relaxed">
            Enter your email and we&apos;ll send you a recovery link.
          </p>
        </div>

        {/* Form Container */}
        <form onSubmit={handleSubmit} className="space-y-4">
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
              disabled={status === "submitting"}
              className="h-12 rounded-xl border-[#2A170D]/15 bg-white font-sans text-sm text-[#2A170D] placeholder-[#6B5646]/50 shadow-[0_1px_3px_rgba(42,23,13,0.04)] focus:border-[#8A3513] focus:bg-white focus:ring-4 focus:ring-[#8A3513]/10 transition-all"
              required
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
            disabled={!email.trim() || status === "submitting"}
            className="btn w-full !py-3.5 !text-[15px] !font-semibold mt-3 justify-center disabled:opacity-50 disabled:pointer-events-none cursor-pointer"
          >
            {status === "submitting" ? (
              <MaterialIcon
                name="progress_activity"
                size={18}
                className="animate-spin"
              />
            ) : (
              "Send reset link →"
            )}
          </button>
        </form>

        {/* Footer Link */}
        <p className="mt-8 text-center text-xs text-[#6B5646]">
          Remember your password?{" "}
          <Link
            href="/auth/login"
            className="font-semibold text-[#8A3513] underline underline-offset-4 hover:text-[#6e2a10] transition-colors"
          >
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
