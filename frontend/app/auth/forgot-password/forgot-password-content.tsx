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
      <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#FBF7F0] px-6 py-12 [background:radial-gradient(1000px_600px_at_50%_-10%,#F6DCC2,transparent_70%)]">
        {/* Ambient background orbs */}
        <div className="orb -left-20 top-20 h-[380px] w-[380px] bg-[#E9A878]" />
        <div className="orb -right-16 bottom-20 h-[340px] w-[340px] bg-[#C9733F] [animation-delay:-5s]" />

        <div className="relative z-10 w-full max-w-[420px] rounded-[32px] border border-white/80 bg-white/70 p-8 md:p-10 shadow-[0_1px_0_#fff_inset,0_30px_60px_-25px_rgba(90,40,10,0.22)] backdrop-blur-xl animate-in fade-in zoom-in-95 duration-300">
          <div className="mb-8 text-center">
            <Link href="/" className="inline-flex items-center gap-1 font-['Bricolage_Grotesque'] text-3xl font-bold tracking-tight text-[#2A170D] transition-transform hover:scale-105 mb-5">
              Kova<span className="text-[#D58A56]">.</span>
            </Link>
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-[#8A3513]/10 border border-[#8A3513]/20 text-[#8A3513]">
              <MaterialIcon name="mail" size={24} />
            </div>
            <h1 className="font-['Bricolage_Grotesque'] text-3xl md:text-4xl font-bold tracking-tight text-[#2A170D] mb-2">
              Check your <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">email.</em>
            </h1>
            <p className="text-sm text-[#6B5646]">
              We sent a password reset link to{" "}
              <span className="font-medium text-[#2A170D]">{email}</span>.
            </p>
          </div>

          <p className="mt-6 text-center text-xs text-[#6B5646]">
            Didn&apos;t receive it?{" "}
            <button
              onClick={() => {
                setSent(false);
                setEmail("");
              }}
              className="font-semibold text-[#8A3513] underline underline-offset-4 hover:text-[#6e2a10] transition-colors"
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
            Forgot <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">password?</em>
          </h1>
          <p className="text-sm text-[#6B5646]">
            Enter your email and we&apos;ll send you a reset link.
          </p>
        </div>

        {/* Form Container */}
        <form onSubmit={handleSubmit} className="space-y-4">
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
              disabled={status === "submitting"}
              className="h-12 rounded-xl border-[#2A170D]/15 bg-white/80 font-sans text-sm text-[#2A170D] placeholder-[#6B5646]/50 shadow-sm focus:border-[#8A3513] focus:ring-2 focus:ring-[#8A3513]/15"
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
            className="btn-pill w-full !py-3.5 !text-sm mt-2 disabled:opacity-50 disabled:pointer-events-none"
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
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
