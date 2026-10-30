"use client";

import { useEffect, useMemo, useState } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";
import type { DocHeading } from "@/lib/docs";

interface DocsTocProps {
  headings: DocHeading[];
}

interface TocNode {
  id: string;
  text: string;
  level: number;
  children: TocNode[];
}

function buildTree(headings: DocHeading[]): TocNode[] {
  const roots: TocNode[] = [];
  let lastH2: TocNode | null = null;

  for (const h of headings) {
    const node: TocNode = { id: h.id, text: h.text, level: h.level, children: [] };
    if (h.level === 2) {
      roots.push(node);
      lastH2 = node;
    } else if (h.level === 3 && lastH2) {
      lastH2.children.push(node);
    } else {
      roots.push(node);
      lastH2 = null;
    }
  }

  return roots;
}

function TocLink({
  node,
  activeId,
  nested,
}: {
  node: TocNode;
  activeId: string;
  nested?: boolean;
}) {
  const isActive = activeId === node.id;
  const isParentActive =
    !isActive && node.children.some((c) => c.id === activeId);

  return (
    <li>
      <a
        href={`#${node.id}`}
        className={cn(
          "block py-1 border-l-2 transition-colors hover:text-foreground",
          nested ? "pl-5 text-[11.5px]" : "pl-3",
          isActive || isParentActive
            ? "border-l-primary text-primary font-medium"
            : "border-l-transparent text-muted-foreground"
        )}
      >
        {node.text}
      </a>
      {node.children.length > 0 && (
        <ul className="mt-0">
          {node.children.map((child) => (
            <TocLink key={child.id} node={child} activeId={activeId} nested />
          ))}
        </ul>
      )}
    </li>
  );
}

export function DocsToc({ headings }: DocsTocProps) {
  const [activeId, setActiveId] = useState<string>("");

  const tree = useMemo(() => buildTree(headings), [headings]);

  useEffect(() => {
    if (headings.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveId(entry.target.id);
            break;
          }
        }
      },
      {
        rootMargin: "-80px 0% -60% 0%",
        threshold: 0.1,
      }
    );

    headings.forEach((heading) => {
      const el = document.getElementById(heading.id);
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, [headings]);

  if (headings.length === 0) {
    return null;
  }

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <nav aria-label="Table of contents" className="text-xs space-y-1">
      <div className="font-semibold text-foreground uppercase tracking-wider flex items-center gap-1.5 mb-3 sticky top-0 bg-background/95 backdrop-blur pb-1">
        <MaterialIcon name="format_list_bulleted" size={14} className="text-primary/70" />
        <span>On this page</span>
      </div>

      <ul className="space-y-0.5">
        {tree.map((node) => (
          <TocLink key={node.id} node={node} activeId={activeId} />
        ))}
      </ul>

      <div className="pt-4 mt-2 border-t border-border/60">
        <button
          type="button"
          onClick={scrollToTop}
          className="text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1 text-[11px] cursor-pointer"
        >
          <MaterialIcon name="arrow_upward" size={12} />
          <span>Back to top</span>
        </button>
      </div>
    </nav>
  );
}
