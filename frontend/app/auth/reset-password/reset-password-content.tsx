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
      <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#FBF7F0] px-6 py-12 [background:radial-gradient(1000px_600px_at_50%_-10%,#F6DCC2,transparent_70%)]">
        <div className="orb -left-20 top-20 h-[380px] w-[380px] bg-[#E9A878]" />
        <div className="orb -right-16 bottom-20 h-[340px] w-[340px] bg-[#C9733F] [animation-delay:-5s]" />
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
              <MaterialIcon name="error" size={24} />
            </div>
            <h1 className="font-['Bricolage_Grotesque'] text-3xl md:text-4xl font-bold tracking-tight text-[#2A170D] mb-2">
              Link <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">expired.</em>
            </h1>
            <p className="text-sm text-[#6B5646]">
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
      <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#FBF7F0] px-6 py-12 [background:radial-gradient(1000px_600px_at_50%_-10%,#F6DCC2,transparent_70%)]">
        {/* Ambient background orbs */}
        <div className="orb -left-20 top-20 h-[380px] w-[380px] bg-[#E9A878]" />
        <div className="orb -right-16 bottom-20 h-[340px] w-[340px] bg-[#C9733F] [animation-delay:-5s]" />

        <div className="relative z-10 w-full max-w-[420px] rounded-[32px] border border-white/80 bg-white/70 p-8 md:p-10 shadow-[0_1px_0_#fff_inset,0_30px_60px_-25px_rgba(90,40,10,0.22)] backdrop-blur-xl animate-in fade-in zoom-in-95 duration-300">
          <div className="mb-8 text-center">
            <Link href="/" className="inline-flex items-center gap-1 font-['Bricolage_Grotesque'] text-3xl font-bold tracking-tight text-[#2A170D] transition-transform hover:scale-105 mb-5">
              Kova<span className="text-[#D58A56]">.</span>
            </Link>
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-[#00A86B]/10 border border-[#00A86B]/20 text-[#00A86B]">
              <MaterialIcon name="check_circle" size={24} />
            </div>
            <h1 className="font-['Bricolage_Grotesque'] text-3xl md:text-4xl font-bold tracking-tight text-[#2A170D] mb-2">
              Password <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">updated.</em>
            </h1>
            <p className="text-sm text-[#6B5646]">
              Your password has been reset. You can now sign in.
            </p>
          </div>

          <button
            onClick={() => router.push("/auth/login")}
            className="btn-pill w-full !py-3.5 !text-sm mt-2 flex items-center justify-center gap-2"
          >
            <span>Sign in</span>
            <MaterialIcon name="arrow_forward" size={18} />
          </button>
        </div>
      </div>
    );
  }

  // Form state — enter new password
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
            Set new <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">password.</em>
          </h1>
          <p className="text-sm text-[#6B5646]">
            Choose a strong password for your account.
          </p>
        </div>

        {/* Form Container */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="password" className="font-['DM_Mono'] text-xs font-medium uppercase tracking-wider text-[#6B5646]">
              New password
            </label>
            <PasswordInput
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 6 characters"
              autoComplete="new-password"
              disabled={status === "submitting"}
              className="h-12 rounded-xl border-[#2A170D]/15 bg-white/80 font-sans text-sm text-[#2A170D] placeholder-[#6B5646]/50 shadow-sm focus:border-[#8A3513] focus:ring-2 focus:ring-[#8A3513]/15"
              required
              minLength={6}
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="confirmPassword" className="font-['DM_Mono'] text-xs font-medium uppercase tracking-wider text-[#6B5646]">
              Confirm password
            </label>
            <PasswordInput
              id="confirmPassword"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Re-enter password"
              autoComplete="new-password"
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
            disabled={!password.trim() || !confirmPassword.trim() || status === "submitting"}
            className="btn-pill w-full !py-3.5 !text-sm mt-2 disabled:opacity-50 disabled:pointer-events-none"
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
