"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";
import { getMe } from "@/lib/api/onboarding";
import { getExecutions } from "@/lib/api/executions";
import type { ExecutionDetail } from "@/lib/types";

interface NavItem {
  label: string;
  href: string;
  icon: string;
}

const primaryNav: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: "dashboard" },
  { label: "Explore Studio", href: "/explore", icon: "explore" },
  { label: "Flows", href: "/flows", icon: "account_tree" },
  { label: "Proof & Runs", href: "/executions", icon: "verified" },
  { label: "Projects", href: "/projects", icon: "folder" },
];

const secondaryNav: NavItem[] = [
  { label: "Credentials", href: "/credentials", icon: "key" },
  { label: "Organization", href: "/organization", icon: "group" },
  { label: "Settings", href: "/settings", icon: "settings" },
];

function NavButton({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <Link
      href={item.href}
      className={cn(
        "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] leading-5 transition-colors duration-150 select-none",
        active
          ? "bg-[var(--sand)] font-semibold text-foreground"
          : "font-normal text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
      )}
      aria-current={active ? "page" : undefined}
    >
      <MaterialIcon
        name={item.icon}
        size={17}
        className={cn(active ? "text-[var(--rust)]" : "text-muted-foreground/80")}
      />
      <span className="truncate">{item.label}</span>
    </Link>
  );
}

export function AppSidebar({ organizationName }: { organizationName?: string }) {
  const pathname = usePathname();
  const [onboardingStep, setOnboardingStep] = useState<number | null>(null);
  const [recent, setRecent] = useState<ExecutionDetail[]>([]);

  useEffect(() => {
    let mounted = true;
    getMe()
      .then((user) => {
        if (mounted && user) {
          setOnboardingStep(user.onboarding_step ?? 0);
        }
      })
      .catch(() => {
        // Silently ignore if unauthenticated or offline
      });
    return () => {
      mounted = false;
    };
  }, [pathname]);

  useEffect(() => {
    let mounted = true;
    getExecutions()
      .then((items) => {
        if (mounted) setRecent(items.slice(0, 3));
      })
      .catch(() => {
        // Recent runs are optional chrome; ignore fetch failures.
      });
    return () => {
      mounted = false;
    };
  }, []);

  const isActive = (href: string) => {
    if (href === "/dashboard") return pathname === "/dashboard";
    return pathname.startsWith(href);
  };

  return (
    <aside className="hidden lg:fixed lg:inset-y-0 lg:left-0 lg:z-40 lg:flex lg:w-60 lg:flex-col border-r border-border bg-card select-none">
      <div className="flex h-14 items-center px-4">
        <Link href="/dashboard" className="flex items-center gap-2.5" aria-label="Kova home">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--rust)] font-heading text-base font-bold leading-none text-[var(--background)]">
            K
          </span>
          <span className="font-heading text-lg font-bold tracking-tight text-foreground">
            Kova
          </span>
        </Link>
      </div>

      <div className="px-3 pb-3">
        <Link
          href="/organization"
          className="flex items-center gap-2.5 rounded-xl border border-border/80 bg-background/70 px-2.5 py-2 transition-colors hover:bg-background"
        >
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[var(--sand)] text-[11px] font-semibold uppercase text-[var(--rust)]">
            {(organizationName || "Kova").slice(0, 2)}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[9px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
              Workspace
            </span>
            <span className="block truncate text-xs font-semibold text-foreground">
              {organizationName || "Personal"}
            </span>
          </span>
          <MaterialIcon name="unfold_more" size={14} className="text-muted-foreground" />
        </Link>
      </div>

      {/* Primary Application Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-2" aria-label="Main navigation">
        <div className="flex flex-col gap-0.5">
          {primaryNav.map((item) => (
            <NavButton key={item.href} item={item} active={isActive(item.href)} />
          ))}
        </div>

        {recent.length > 0 && (
          <div className="mt-6">
            <div className="flex items-center justify-between px-2.5 pb-1.5">
              <span className="text-[9px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/70">
                Recent
              </span>
              <Link href="/executions" className="text-[10px] text-muted-foreground hover:text-foreground">
                View all
              </Link>
            </div>
            <div className="flex flex-col gap-0.5">
              {recent.map((execution) => (
                <Link
                  key={execution.id}
                  href="/executions"
                  className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[12px] text-muted-foreground transition-colors hover:bg-secondary/60 hover:text-foreground"
                >
                  <span
                    className={cn(
                      "h-1.5 w-1.5 shrink-0 rounded-full",
                      execution.status === "completed" && "bg-emerald-500",
                      execution.status === "failed" && "bg-destructive",
                      execution.status === "blocked" && "bg-amber-500",
                      !["completed", "failed", "blocked"].includes(execution.status) && "bg-[var(--clay)]"
                    )}
                  />
                  <span className="truncate">{execution.missionName || "Untitled run"}</span>
                </Link>
              ))}
            </div>
          </div>
        )}
      </nav>

      {/* Complete setup card */}
      {onboardingStep !== null && onboardingStep < 4 && (
        <div className="px-3 pb-3">
          <Link
            href="/onboarding"
            className="flex items-center justify-between rounded-xl border border-primary/20 bg-primary/5 p-3 hover:bg-primary/10 transition-colors"
          >
            <div className="flex items-center gap-2">
              <MaterialIcon name="checklist" size={18} className="text-primary" />
              <div className="flex flex-col text-left">
                <span className="text-xs font-semibold text-primary">Complete setup</span>
                <span className="text-[10px] text-muted-foreground">Step {onboardingStep + 1} of 4</span>
              </div>
            </div>
            <MaterialIcon name="chevron_right" size={16} className="text-primary/70" />
          </Link>
        </div>
      )}

      {/* Secondary System Navigation */}
      <nav className="border-t border-border px-3 py-3" aria-label="Secondary navigation">
        <div className="flex flex-col gap-1">
          {secondaryNav.map((item) => (
            <NavButton key={item.href} item={item} active={isActive(item.href)} />
          ))}
        </div>
      </nav>
    </aside>
  );
}

