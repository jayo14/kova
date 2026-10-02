"use client";

import { useRouter } from "next/navigation";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import { createClient } from "@/lib/auth/client";
import { clearPendingIntent } from "@/lib/auth/pending-intent";
import type { User } from "@supabase/supabase-js";

interface UserMenuProps {
  user: User;
}

export function UserMenu({ user }: UserMenuProps) {
  const router = useRouter();

  const displayName =
    user.user_metadata?.name || user.email?.split("@")[0] || "User";
  const userEmail = user.email || "";

  const handleSignOut = async () => {
    try {
      const supabase = createClient();
      await supabase.auth.signOut();
      clearPendingIntent();
    } catch {
      // Continue cleanup
    }
    router.push("/");
    router.refresh();
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="sm"
            className="gap-2.5 px-2.5 h-9 rounded-xl hover:bg-secondary/40 select-none"
            aria-label="Open user menu"
          />
        }
      >
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-caption font-semibold text-primary">
          {displayName.charAt(0).toUpperCase()}
        </span>
        <span className="hidden text-body-sm font-medium text-foreground sm:inline truncate max-w-[120px]">
          {displayName}
        </span>
        <MaterialIcon
          name="expand_more"
          size={14}
          className="text-muted-foreground"
        />
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-56 p-1.5 shadow-md">
        <DropdownMenuLabel className="px-3 py-2">
          <p className="text-body-sm font-semibold text-foreground truncate">
            {displayName}
          </p>
          {userEmail && (
            <p className="text-caption text-muted-foreground truncate">
              {userEmail}
            </p>
          )}
        </DropdownMenuLabel>

        <DropdownMenuSeparator className="my-1" />

        <DropdownMenuItem
          onClick={() => router.push("/dashboard")}
          className="gap-2.5 px-3 py-2 cursor-pointer text-body-sm"
        >
          <MaterialIcon name="dashboard" size={16} className="text-muted-foreground" />
          <span>Dashboard</span>
        </DropdownMenuItem>

        <DropdownMenuItem
          onClick={() => router.push("/projects")}
          className="gap-2.5 px-3 py-2 cursor-pointer text-body-sm"
        >
          <MaterialIcon name="folder" size={16} className="text-muted-foreground" />
          <span>Projects</span>
        </DropdownMenuItem>

        <DropdownMenuItem
          onClick={() => router.push("/settings")}
          className="gap-2.5 px-3 py-2 cursor-pointer text-body-sm"
        >
          <MaterialIcon name="settings" size={16} className="text-muted-foreground" />
          <span>Settings</span>
        </DropdownMenuItem>

        <DropdownMenuSeparator className="my-1" />

        <DropdownMenuItem
          onClick={handleSignOut}
          variant="destructive"
          className="gap-2.5 px-3 py-2 cursor-pointer text-body-sm text-destructive hover:bg-destructive/10"
        >
          <MaterialIcon name="logout" size={16} className="text-destructive" />
          <span>Sign out</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
