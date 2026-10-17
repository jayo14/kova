"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";
import type { DocNavigationGroup } from "@/lib/docs";

interface DocsSidebarProps {
  navigation: DocNavigationGroup[];
  className?: string;
  onLinkClick?: () => void;
}

const groupIcons: Record<string, string> = {
  "Getting Started": "rocket_launch",
  "CI/CD & Integrations": "integration_instructions",
  "Platform & Ops": "tune",
  Reference: "menu_book",
};

export function DocsSidebar({ navigation, className, onLinkClick }: DocsSidebarProps) {
  const pathname = usePathname();

  return (
    <nav className={cn("space-y-6 text-sm", className)}>
      {navigation.map((group) => {
        const iconName = groupIcons[group.group] || "folder";

        return (
          <div key={group.group} className="space-y-2">
            <div className="flex items-center gap-2 px-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              <MaterialIcon name={iconName} size={14} className="text-primary/70" />
              <span>{group.group}</span>
            </div>

            <ul className="space-y-1">
              {group.pages.map((page) => {
                const isActive = pathname === page.href;

                return (
                  <li key={page.slug}>
                    <Link
                      href={page.href}
                      onClick={onLinkClick}
                      className={cn(
                        "group flex items-center justify-between px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                        isActive
                          ? "bg-primary/10 text-primary font-semibold"
                          : "text-muted-foreground hover:text-foreground hover:bg-secondary/40"
                      )}
                    >
                      <span className="truncate">{page.title}</span>
                      {isActive && (
                        <div className="h-1.5 w-1.5 rounded-full bg-primary shrink-0" />
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}

      {/* Helpful links box at bottom of sidebar */}
      <div className="rounded-xl border border-border/80 bg-secondary/20 p-3 text-xs space-y-2">
        <div className="font-semibold text-foreground flex items-center gap-1.5">
          <MaterialIcon name="support_agent" size={15} className="text-primary" />
          <span>Need help?</span>
        </div>
        <p className="text-muted-foreground text-[11px] leading-relaxed">
          Join our developer community or inspect real CI runs in the dashboard.
        </p>
        <div className="pt-1 flex flex-col gap-1 text-[11px]">
          <Link href="/dashboard" className="text-primary hover:underline flex items-center gap-1">
            <span>Explore live executions</span>
            <MaterialIcon name="arrow_forward" size={11} />
          </Link>
          <a
            href="https://github.com/jayo14/kova/issues"
            target="_blank"
            rel="noreferrer"
            className="text-muted-foreground hover:text-foreground flex items-center gap-1"
          >
            <span>Report an issue on GitHub</span>
            <MaterialIcon name="open_in_new" size={11} className="opacity-70" />
          </a>
        </div>
      </div>
    </nav>
  );
}
