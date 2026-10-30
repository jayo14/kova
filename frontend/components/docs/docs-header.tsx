"use client";

import Link from "next/link";
import { useState } from "react";
import { Logo } from "@/components/shared/logo";
import { MaterialIcon } from "@/components/shared/material-icon";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { DocsSearchDialog } from "./docs-search-dialog";
import type { DocNavigationGroup } from "@/lib/docs";

interface DocsHeaderProps {
  navigation: DocNavigationGroup[];
  onToggleMobileNav?: () => void;
}

export function DocsHeader({ navigation, onToggleMobileNav }: DocsHeaderProps) {
  const [searchOpen, setSearchOpen] = useState(false);

  return (
    <>
      <header className="sticky top-0 z-40 w-full border-b border-border/60 bg-background/85 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          {/* Left: Brand + Mobile Menu Button */}
          <div className="flex items-center gap-3">
            {onToggleMobileNav && (
              <button
                type="button"
                onClick={onToggleMobileNav}
                className="lg:hidden p-1.5 text-muted-foreground hover:text-foreground rounded-md hover:bg-secondary/60 cursor-pointer"
                aria-label="Toggle navigation menu"
              >
                <MaterialIcon name="menu" size={20} />
              </button>
            )}

            <Link href="/" className="flex items-center gap-2">
              <Logo size="md" />
              <span className="rounded-md bg-primary/10 px-1.5 py-0.5 text-[11px] font-semibold text-primary uppercase tracking-wide border border-primary/20">
                Docs
              </span>
            </Link>
          </div>

          {/* Center: Search Palette Trigger */}
          <div className="hidden sm:flex flex-1 max-w-md mx-6">
            <button
              type="button"
              onClick={() => setSearchOpen(true)}
              className="w-full flex items-center justify-between gap-3 px-3 py-1.5 text-sm text-muted-foreground bg-secondary/40 hover:bg-secondary/70 border border-border/80 rounded-xl transition-all cursor-pointer shadow-2xs"
            >
              <div className="flex items-center gap-2">
                <MaterialIcon name="search" size={16} className="text-muted-foreground/70" />
                <span className="text-xs">Search documentation...</span>
              </div>
              <kbd className="hidden md:inline-flex items-center gap-0.5 rounded border border-border/80 bg-background px-1.5 py-0.5 text-[10px] font-mono font-medium text-muted-foreground">
                <span className="text-xs">⌘</span>K
              </kbd>
            </button>
          </div>

          {/* Right: Quick Links + CTA */}
          <div className="flex items-center gap-2 sm:gap-3">
            <button
              type="button"
              onClick={() => setSearchOpen(true)}
              className="sm:hidden p-1.5 text-muted-foreground hover:text-foreground rounded-md hover:bg-secondary/60 cursor-pointer"
              aria-label="Search docs"
            >
              <MaterialIcon name="search" size={20} />
            </button>

            <nav className="hidden md:flex items-center gap-4 text-xs font-medium text-muted-foreground">
              <Link href="/dashboard" className="hover:text-foreground transition-colors">
                Platform
              </Link>
              <Link href="/explore" className="hover:text-foreground transition-colors">
                Explore
              </Link>
              <Link href="/status" className="hover:text-foreground transition-colors">
                Status
              </Link>
            </nav>

            <a
              className="github-button"
              href="https://github.com/jayo14/kova"
              data-icon="octicon-star"
              data-size="large"
              data-show-count="true"
              aria-label="Star jayo14/kova on GitHub"
            >
              Star
            </a>

            <Link
              href="/dashboard"
              className={cn(
                buttonVariants({ size: "sm" }),
                "h-8 text-xs font-semibold px-3 rounded-lg gap-1.5 inline-flex items-center"
              )}
            >
              <span>Open App</span>
              <MaterialIcon name="arrow_forward" size={14} />
            </Link>
          </div>
        </div>
      </header>

      <DocsSearchDialog
        navigation={navigation}
        open={searchOpen}
        onOpenChange={setSearchOpen}
      />
    </>
  );
}
