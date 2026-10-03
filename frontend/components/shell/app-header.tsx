"use client";

import { Logo } from "@/components/shared/logo";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { UserMenu } from "./user-menu";
import type { User } from "@/lib/auth/custom";

interface AppHeaderProps {
  user: User;
  organizationName?: string;
  onMobileNavOpen: () => void;
}

export function AppHeader({
  user,
  organizationName,
  onMobileNavOpen,
}: AppHeaderProps) {
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-background/80 px-4 backdrop-blur-sm lg:px-6">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon-sm"
          className="lg:hidden"
          onClick={onMobileNavOpen}
          aria-label="Open navigation"
        >
          <MaterialIcon name="menu" size={20} />
        </Button>
        <a href="/dashboard" className="flex items-center lg:hidden" aria-label="Kova home">
          <Logo size="sm" />
        </a>

        {organizationName && (
          <div className="hidden lg:flex items-center gap-2 text-body-sm">
            <span className="font-semibold text-foreground truncate max-w-[200px]">
              {organizationName}
            </span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <UserMenu user={user} />
      </div>
    </header>
  );
}
