"use client";

import { useState } from "react";
import { DocsHeader } from "./docs-header";
import { DocsSidebar } from "./docs-sidebar";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";
import type { DocNavigationGroup } from "@/lib/docs";

interface DocsShellProps {
  navigation: DocNavigationGroup[];
  children: React.ReactNode;
}

export function DocsShell({ navigation, children }: DocsShellProps) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground antialiased selection:bg-primary/20">
      <DocsHeader
        navigation={navigation}
        onToggleMobileNav={() => setMobileNavOpen(!mobileNavOpen)}
      />

      {/* Mobile Drawer Backdrop & Drawer */}
      {mobileNavOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="fixed inset-0 bg-black/60 backdrop-blur-xs transition-opacity"
            onClick={() => setMobileNavOpen(false)}
          />
          <div className="fixed inset-y-0 left-0 w-3/4 max-w-xs bg-background p-6 shadow-2xl flex flex-col justify-between overflow-y-auto border-r border-border">
            <div className="space-y-6">
              <div className="flex items-center justify-between pb-3 border-b border-border">
                <span className="font-bold text-sm tracking-tight text-foreground">Documentation</span>
                <button
                  type="button"
                  onClick={() => setMobileNavOpen(false)}
                  className="p-1 rounded-md text-muted-foreground hover:text-foreground cursor-pointer"
                >
                  <MaterialIcon name="close" size={18} />
                </button>
              </div>
              <DocsSidebar
                navigation={navigation}
                onLinkClick={() => setMobileNavOpen(false)}
              />
            </div>
          </div>
        </div>
      )}

      {/* Main Container */}
      <div className="mx-auto flex w-full max-w-7xl flex-1 px-4 sm:px-6 lg:px-8">
        {/* Desktop Sticky Left Sidebar */}
        <aside className="hidden lg:block w-64 shrink-0 border-r border-border/40 py-8 pr-6 sticky top-14 h-[calc(100vh-3.5rem)] overflow-y-auto">
          <DocsSidebar navigation={navigation} />
        </aside>

        {/* Dynamic Doc Page Content */}
        <main className="flex-1 min-w-0 py-8 lg:px-10">
          {children}
        </main>
      </div>

      {/* Docs Footer */}
      <footer className="border-t border-border/40 py-8 bg-secondary/10 mt-auto">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <span>© {new Date().getFullYear()} Kova Technologies, Inc.</span>
            <span>•</span>
            <span>Autonomous Software Testing</span>
          </div>
          <div className="flex items-center gap-4">
            <a href="https://status.kova.dev" target="_blank" rel="noreferrer" className="hover:text-foreground transition-colors">
              Status
            </a>
            <a href="https://github.com/jayo14/kova" target="_blank" rel="noreferrer" className="hover:text-foreground transition-colors">
              GitHub
            </a>
            <a href="/dashboard" className="text-primary hover:underline font-medium">
              Platform
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
