"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

interface ProductLogoProps {
  project: {
    name: string;
    baseUrl?: string;
    logoUrl?: string | null;
  };
  size?: "sm" | "md" | "lg";
  className?: string;
}

function getFaviconUrl(url?: string): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url.startsWith("http") ? url : `https://${url}`);
    const host = parsed.hostname.replace(/^www\d*\./, "");
    if (!host) return null;
    return `https://www.google.com/s2/favicons?domain=${host}&sz=128`;
  } catch {
    return null;
  }
}

function getInitials(name: string): string {
  if (!name) return "P";
  const clean = name.trim().replace(/^https?:\/\//i, "").replace(/^www\d*\./i, "");
  const parts = clean.split(/[\s-_]+/);
  if (parts.length >= 2 && parts[0][0] && parts[1][0]) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return clean.slice(0, Math.min(clean.length, 2)).toUpperCase();
}

export function ProductLogo({
  project,
  size = "md",
  className,
}: ProductLogoProps) {
  const fallbackFavicon = getFaviconUrl(project.baseUrl);
  const initialSrc = project.logoUrl || fallbackFavicon;

  const [src, setSrc] = useState<string | null>(initialSrc);
  const [hasError, setHasError] = useState(false);

  const handleError = () => {
    // If custom logo failed, fall back to Google favicon
    if (src && src !== fallbackFavicon && fallbackFavicon) {
      setSrc(fallbackFavicon);
    } else {
      setSrc(null);
      setHasError(true);
    }
  };

  const sizeClasses = {
    sm: "size-7 rounded-lg text-xs",
    md: "size-10 rounded-xl text-xs",
    lg: "size-12 rounded-xl text-sm font-semibold",
  }[size];

  const initials = getInitials(project.name);

  return (
    <div
      className={cn(
        "relative flex shrink-0 items-center justify-center border border-border/80 bg-muted/40 shadow-2xs overflow-hidden select-none transition-transform group-hover:scale-[1.02]",
        sizeClasses,
        className
      )}
      aria-label={`${project.name} logo`}
    >
      {src && !hasError ? (
        <img
          src={src}
          alt={`${project.name} logo`}
          className="size-full object-contain p-1.5 transition-opacity duration-200"
          onError={handleError}
          loading="lazy"
        />
      ) : (
        <span className="font-mono font-medium text-foreground/80 tracking-tight">
          {initials}
        </span>
      )}
    </div>
  );
}
