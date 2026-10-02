"use client";

import { useEffect, useState, useMemo, type ReactNode } from "react";
import { AppSidebar } from "./app-sidebar";
import { AppHeader } from "./app-header";
import { MobileNav } from "./mobile-nav";
import { useAuthStore } from "@/lib/store";
import { resolveUserOrganization } from "@/lib/auth/organization";
import type { User } from "@supabase/supabase-js";

interface AppShellProps {
  children: ReactNode;
  user: User;
  organizationName?: string;
}

export function AppShell({ children, user, organizationName }: AppShellProps) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const setUser = useAuthStore((s) => s.setUser);

  useEffect(() => {
    setUser(user);
  }, [user, setUser]);

  const activeWorkspaceName = useMemo(() => {
    if (organizationName) return organizationName;
    const org = resolveUserOrganization(user);
    return org.name;
  }, [user, organizationName]);

  return (
    <div className="min-h-screen bg-background">
      <AppSidebar />
      <MobileNav open={mobileNavOpen} onOpenChange={setMobileNavOpen} />

      <div className="lg:pl-56">
        <AppHeader
          user={user}
          organizationName={activeWorkspaceName}
          onMobileNavOpen={() => setMobileNavOpen(true)}
        />
        <main className="flex-1">{children}</main>
      </div>
    </div>
  );
}
