import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";

interface BreadcrumbsProps {
  parentHref: string;
  parentLabel: string;
  currentLabel: string;
  className?: string;
}

export function Breadcrumbs({
  parentHref,
  parentLabel,
  currentLabel,
  className,
}: BreadcrumbsProps) {
  return (
    <nav
      aria-label="Breadcrumb"
      className={cn(
        "flex items-center gap-1.5 text-body-sm text-muted-foreground",
        className
      )}
    >
      <Link
        href={parentHref}
        className="inline-flex items-center gap-1 hover:text-foreground transition-colors"
      >
        <MaterialIcon name="arrow_back" size={16} />
        <span>{parentLabel}</span>
      </Link>
      <span className="text-border" aria-hidden="true">/</span>
      <span className="text-foreground font-medium truncate max-w-[200px] sm:max-w-xs">
        {currentLabel}
      </span>
    </nav>
  );
}
