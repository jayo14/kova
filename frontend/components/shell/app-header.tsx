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
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border/80 bg-background/90 px-4 backdrop-blur-md lg:px-6">
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
          <div className="hidden items-center gap-2 text-[12px] text-muted-foreground lg:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            <span className="max-w-[240px] truncate font-medium">{organizationName}</span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <UserMenu user={user} />
      </div>
    </header>
  );
}
