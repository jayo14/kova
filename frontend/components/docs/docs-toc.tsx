"use client";

import { useEffect, useState } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";
import type { DocHeading } from "@/lib/docs";

interface DocsTocProps {
  headings: DocHeading[];
}

export function DocsToc({ headings }: DocsTocProps) {
  const [activeId, setActiveId] = useState<string>("");

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
    <div className="space-y-4 text-xs">
      <div className="font-semibold text-foreground uppercase tracking-wider flex items-center gap-1.5">
        <MaterialIcon name="format_list_bulleted" size={14} className="text-primary/70" />
        <span>On this page</span>
      </div>

      <ul className="space-y-2 border-l border-border/60 pl-3">
        {headings.map((heading) => {
          const isActive = activeId === heading.id;

          return (
            <li key={heading.id} className={cn(heading.level === 3 ? "pl-2" : "")}>
              <a
                href={`#${heading.id}`}
                className={cn(
                  "block truncate transition-colors hover:text-foreground",
                  isActive
                    ? "font-semibold text-primary"
                    : "text-muted-foreground"
                )}
              >
                {heading.text}
              </a>
            </li>
          );
        })}
      </ul>

      <div className="pt-2">
        <button
          type="button"
          onClick={scrollToTop}
          className="text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1 text-[11px] cursor-pointer"
        >
          <MaterialIcon name="arrow_upward" size={12} />
          <span>Back to top</span>
        </button>
      </div>
    </div>
  );
}
