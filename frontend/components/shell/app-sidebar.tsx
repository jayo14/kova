"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  href: string;
  icon: string;
}

const primaryNav: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: "dashboard" },
  { label: "Projects", href: "/projects", icon: "folder" },
  { label: "Flows", href: "/flows", icon: "account_tree" },
  { label: "Executions", href: "/executions", icon: "play_circle" },
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
        "flex items-center gap-3 rounded-xl px-3 py-2 text-body-sm transition-all duration-150 select-none",
        active
          ? "bg-primary/8 text-primary font-semibold shadow-2xs"
          : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground font-normal"
      )}
      aria-current={active ? "page" : undefined}
    >
      <MaterialIcon
        name={item.icon}
        size={18}
        className={cn(active ? "text-primary font-bold" : "text-muted-foreground")}
      />
      <span>{item.label}</span>
    </Link>
  );
}

export function AppSidebar() {
  const pathname = usePathname();

  const isActive = (href: string) => {
    if (href === "/dashboard") return pathname === "/dashboard";
    return pathname.startsWith(href);
  };

  return (
    <aside className="hidden lg:fixed lg:inset-y-0 lg:left-0 lg:z-40 lg:flex lg:w-56 lg:flex-col border-r border-border bg-background/95 select-none">
      {/* Kova Wordmark Header */}
      <div className="flex h-14 items-center px-5 border-b border-border">
        <Link href="/dashboard" className="flex items-center gap-2" aria-label="Kova home">
          <span className="text-body-lg font-bold tracking-tight text-foreground font-sans">
            Kova
          </span>
        </Link>
      </div>

      {/* Primary Application Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-4" aria-label="Main navigation">
        <div className="flex flex-col gap-1">
          {primaryNav.map((item) => (
            <NavButton key={item.href} item={item} active={isActive(item.href)} />
          ))}
        </div>
      </nav>

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
