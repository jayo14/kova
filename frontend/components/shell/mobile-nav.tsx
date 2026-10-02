"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
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

interface MobileNavProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function MobileNav({ open, onOpenChange }: MobileNavProps) {
  const pathname = usePathname();

  const isActive = (href: string) => {
    if (href === "/dashboard") return pathname === "/dashboard";
    return pathname.startsWith(href);
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="left" showCloseButton={false} className="w-64 p-0">
        <SheetHeader className="border-b border-border px-5 py-4 text-left">
          <SheetTitle className="sr-only">Mobile navigation</SheetTitle>
          <Link
            href="/dashboard"
            onClick={() => onOpenChange(false)}
            className="flex items-center gap-2"
            aria-label="Kova home"
          >
            <span className="text-body-lg font-bold tracking-tight text-foreground font-sans">
              Kova
            </span>
          </Link>
        </SheetHeader>

        {/* Primary Navigation */}
        <nav className="flex flex-col gap-1 px-3 py-4" aria-label="Mobile main navigation">
          {primaryNav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => onOpenChange(false)}
              className={cn(
                "flex items-center gap-3 rounded-xl px-3 py-2 text-body-sm transition-all select-none",
                isActive(item.href)
                  ? "bg-primary/8 text-primary font-semibold"
                  : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground font-normal"
              )}
              aria-current={isActive(item.href) ? "page" : undefined}
            >
              <MaterialIcon
                name={item.icon}
                size={18}
                className={cn(isActive(item.href) ? "text-primary font-bold" : "text-muted-foreground")}
              />
              <span>{item.label}</span>
            </Link>
          ))}
        </nav>

        <Separator />

        {/* Secondary Navigation */}
        <nav className="flex flex-col gap-1 px-3 py-3" aria-label="Mobile secondary navigation">
          {secondaryNav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => onOpenChange(false)}
              className={cn(
                "flex items-center gap-3 rounded-xl px-3 py-2 text-body-sm transition-all select-none",
                isActive(item.href)
                  ? "bg-primary/8 text-primary font-semibold"
                  : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground font-normal"
              )}
              aria-current={isActive(item.href) ? "page" : undefined}
            >
              <MaterialIcon
                name={item.icon}
                size={18}
                className={cn(isActive(item.href) ? "text-primary font-bold" : "text-muted-foreground")}
              />
              <span>{item.label}</span>
            </Link>
          ))}
        </nav>
      </SheetContent>
    </Sheet>
  );
}
