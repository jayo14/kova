"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { User } from "@supabase/supabase-js";
import { signOut } from "@/lib/auth/settings";
import { AccountSection } from "./account-section";
import { PasswordSection } from "./password-section";
import { AppearanceSection } from "./appearance-section";
import { DangerZone } from "./danger-zone";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";

interface SettingsContentProps {
  user: User;
}

export function SettingsContent({ user }: SettingsContentProps) {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState(user);
  const [signingOut, setSigningOut] = useState(false);

  const handleSignOut = async () => {
    setSigningOut(true);
    try {
      await signOut();
      router.push("/");
      router.refresh();
    } catch {
      setSigningOut(false);
    }
  };

  return (
    <div className="w-full max-w-5xl mx-auto px-6 py-10 md:py-14 animate-in fade-in duration-300">
      <div className="mb-8">
        <h1 className="text-display sm:text-[2.25rem] font-bold text-foreground mb-1.5 tracking-tight">
          Settings
        </h1>
        <p className="text-body-sm text-muted-foreground leading-relaxed">
          Manage your Kova account and preferences.
        </p>
      </div>

      <div className="space-y-8 max-w-3xl">
        {/* Account */}
        <AccountSection user={currentUser} onUserUpdate={setCurrentUser} />

        {/* Password */}
        <PasswordSection />

        {/* Appearance */}
        <AppearanceSection />

        {/* Session */}
        <div className="rounded-2xl border border-border/70 bg-card/50 p-6 transition-colors">
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <h2 className="text-body font-semibold text-foreground">Session</h2>
              <p className="text-caption text-muted-foreground">
                Your current authenticated session details.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleSignOut}
              disabled={signingOut}
              className="gap-1.5 rounded-xl shrink-0"
            >
              {signingOut ? (
                <>
                  <MaterialIcon
                    name="progress_activity"
                    size={14}
                    className="animate-spin"
                  />
                  Signing out...
                </>
              ) : (
                <>
                  <MaterialIcon name="logout" size={14} />
                  Sign out
                </>
              )}
            </Button>
          </div>

          <div className="pt-2 border-t border-border/50">
            <p className="text-caption font-medium uppercase tracking-wider text-muted-foreground/70 mb-1">
              Signed in as
            </p>
            <p className="text-body-sm font-mono text-[13px] text-foreground">
              {currentUser.email}
            </p>
          </div>
        </div>

        {/* Danger Zone */}
        <DangerZone user={currentUser} />
      </div>
    </div>
  );
}
