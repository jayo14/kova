"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { MaterialIcon } from "@/components/shared/material-icon";
import type { DocNavigationGroup } from "@/lib/docs";

interface DocsSearchDialogProps {
  navigation: DocNavigationGroup[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function DocsSearchDialog({
  navigation,
  open,
  onOpenChange,
}: DocsSearchDialogProps) {
  const router = useRouter();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onOpenChange]);

  const handleSelect = (href: string) => {
    onOpenChange(false);
    router.push(href);
  };

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Search Documentation"
      description="Quickly search Kova guides, APIs, and integrations"
    >
      <CommandInput placeholder="Search docs, guides, concepts, integrations... (Cmd+K)" />
      <CommandList className="max-h-[360px] p-2">
        <CommandEmpty className="py-6 text-center text-sm text-muted-foreground">
          No documentation matches found.
        </CommandEmpty>
        {navigation.map((group) => (
          <CommandGroup key={group.group} heading={group.group} className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-2 py-1.5">
            {group.pages.map((page) => (
              <CommandItem
                key={page.slug}
                value={`${group.group} ${page.title} ${page.description || ""}`}
                onSelect={() => handleSelect(page.href)}
                className="flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer hover:bg-secondary/60 transition-colors"
              >
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <MaterialIcon name="description" size={16} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-foreground">{page.title}</div>
                  {page.description && (
                    <div className="text-xs text-muted-foreground truncate">{page.description}</div>
                  )}
                </div>
                <span className="text-[11px] font-mono text-muted-foreground/60">{group.group}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        ))}
      </CommandList>
    </CommandDialog>
  );
}
