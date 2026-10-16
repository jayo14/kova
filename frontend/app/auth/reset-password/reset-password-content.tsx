"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
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
    const code = searchParams.get("code") || searchParams.get("token");
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
      <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#FBF7F0] px-6 py-20 [background:radial-gradient(1000px_600px_at_50%_-10%,#F6DCC2,transparent_70%)]">
        <div className="orb -left-20 top-20 h-[420px] w-[420px] bg-[#E9A878]" />
        <div className="orb -right-16 bottom-20 h-[380px] w-[380px] bg-[#C9733F] [animation-delay:-6s]" />
        <div className="relative z-10 flex flex-col items-center gap-4 text-center">
          <div className="h-10 w-10 rounded-full border-2 border-[#8A3513]/20 border-t-[#8A3513] animate-spin" />
          <p className="font-['DM_Mono'] text-xs uppercase tracking-wider text-[#6B5646]">Verifying reset link...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (phase === "error") {
    return (
      <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#FBF7F0] px-6 py-20 [background:radial-gradient(1000px_600px_at_50%_-10%,#F6DCC2,transparent_70%)]">
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

        <div className="glass relative z-20 w-full max-w-[440px] p-8 sm:p-10 text-left animate-in fade-in zoom-in-95 duration-400">
          <div className="mb-8 text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#8A3513]/10 border border-[#8A3513]/20 text-[#8A3513]">
              <MaterialIcon name="error" size={26} />
            </div>
            <h1 className="font-['Bricolage_Grotesque'] text-4xl sm:text-[42px] font-bold tracking-[-0.035em] text-[#2A170D] mb-2 leading-[1.05]">
              Link <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">expired.</em>
            </h1>
            <p className="text-[15px] text-[#6B5646] leading-relaxed">
              {error || "This reset link is invalid or has expired."}
            </p>
          </div>

          <p className="mt-6 text-center text-xs text-[#6B5646]">
            <Link
              href="/auth/forgot-password"
              className="font-semibold text-[#8A3513] underline underline-offset-4 hover:text-[#6e2a10] transition-colors"
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
      <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#FBF7F0] px-6 py-20 [background:radial-gradient(1000px_600px_at_50%_-10%,#F6DCC2,transparent_70%)]">
        <header className="glass nav absolute top-6 left-1/2 -translate-x-1/2 w-[min(940px,92%)] flex items-center justify-between px-6 py-2.5 rounded-full z-30">
          <Link href="/" className="font-['Bricolage_Grotesque'] text-2xl font-bold tracking-tight text-[#2A170D] transition-transform hover:scale-105">
            Kova<span className="text-[#D58A56]">.</span>
          </Link>
        </header>

        {/* Ambient background orbs */}
        <div className="orb -left-20 top-20 h-[420px] w-[420px] bg-[#E9A878]" />
        <div className="orb -right-16 bottom-20 h-[380px] w-[380px] bg-[#C9733F] [animation-delay:-6s]" />

        <div className="glass relative z-20 w-full max-w-[440px] p-8 sm:p-10 text-left animate-in fade-in zoom-in-95 duration-400">
          <div className="mb-8 text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#3E9B5F]/10 border border-[#3E9B5F]/20 text-[#3E9B5F]">
              <MaterialIcon name="check_circle" size={26} />
            </div>
            <h1 className="font-['Bricolage_Grotesque'] text-4xl sm:text-[42px] font-bold tracking-[-0.035em] text-[#2A170D] mb-2 leading-[1.05]">
              Password <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">updated.</em>
            </h1>
            <p className="text-[15px] text-[#6B5646] leading-relaxed">
              Your password has been reset. You can now sign in.
            </p>
          </div>

          <button
            onClick={() => router.push("/auth/login")}
            className="btn w-full !py-3.5 !text-[15px] !font-semibold mt-2 justify-center cursor-pointer"
          >
            <span>Sign in →</span>
          </button>
        </div>
      </div>
    );
  }

  // Form state — enter new password
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

      {/* Main Glass Form Card */}
      <div className="glass relative z-20 w-full max-w-[440px] p-8 sm:p-10 text-left animate-in fade-in zoom-in-95 duration-400">
        {/* Editorial Eyebrow & Header */}
        <div className="mb-8 text-center">
          <div className="inline-flex items-center gap-2 rounded-full border border-[#2A170D]/10 bg-white/80 px-3.5 py-1 text-xs font-medium text-[#2A170D] shadow-[0_4px_12px_-4px_rgba(90,40,10,0.15)] mb-4">
            <span className="h-2 w-2 rounded-full bg-[#3E9B5F] shadow-[0_0_0_4px_rgba(62,155,95,0.2)]" />
            <span>Secure account</span>
          </div>

          <h1 className="font-['Bricolage_Grotesque'] text-4xl sm:text-[42px] font-bold tracking-[-0.035em] text-[#2A170D] mb-2 leading-[1.05]">
            Set new <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">password.</em>
          </h1>
          <p className="text-[15px] text-[#6B5646] leading-relaxed">
            Choose a strong password for your account.
          </p>
        </div>

        {/* Form Container */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="password" className="block font-['DM_Mono'] text-xs font-medium uppercase tracking-[0.14em] text-[#8A3513]">
              New password
            </label>
            <PasswordInput
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 6 characters"
              autoComplete="new-password"
              disabled={status === "submitting"}
              className="h-12 rounded-xl border-[#2A170D]/15 bg-white font-sans text-sm text-[#2A170D] placeholder-[#6B5646]/50 shadow-[0_1px_3px_rgba(42,23,13,0.04)] focus:border-[#8A3513] focus:bg-white focus:ring-4 focus:ring-[#8A3513]/10 transition-all"
              required
              minLength={6}
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="confirmPassword" className="block font-['DM_Mono'] text-xs font-medium uppercase tracking-[0.14em] text-[#8A3513]">
              Confirm password
            </label>
            <PasswordInput
              id="confirmPassword"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Re-enter password"
              autoComplete="new-password"
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
            disabled={!password.trim() || !confirmPassword.trim() || status === "submitting"}
            className="btn w-full !py-3.5 !text-[15px] !font-semibold mt-3 justify-center disabled:opacity-50 disabled:pointer-events-none cursor-pointer"
          >
            {status === "submitting" ? (
              <MaterialIcon
                name="progress_activity"
                size={18}
                className="animate-spin"
              />
            ) : (
              "Update password →"
            )}
          </button>
        </form>

        {/* Footer Link */}
        <p className="mt-8 text-center text-xs text-[#6B5646]">
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
