import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface FlowEmptyStateProps {
  projectId?: string;
  baseUrl?: string;
}

export function FlowEmptyState({ projectId, baseUrl }: FlowEmptyStateProps) {
  const exploreHref = projectId && baseUrl
    ? `/explore?projectId=${projectId}&url=${encodeURIComponent(baseUrl)}`
    : projectId
    ? `/explore?projectId=${projectId}`
    : "/explore";

  return (
    <section
      aria-label="No missions"
      className="rounded-2xl border border-border/80 bg-secondary/15 px-6 py-14 text-center"
    >
      <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-primary/5 text-primary">
        <MaterialIcon
          name="route"
          size={22}
          className="text-primary/70"
        />
      </div>
      <h3 className="text-body font-semibold text-foreground mb-1.5">
        No missions yet
      </h3>
      <p className="text-body-sm text-muted-foreground max-w-sm mx-auto mb-5 leading-relaxed">
        Give Kova a job and let it figure out how to accomplish it.
      </p>
      <Link
        href={exploreHref}
        className={cn(
          buttonVariants({ variant: "default" }),
          "inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-body-sm font-medium shadow-sm transition-all"
        )}
      >
        <span>Give Kova a job</span>
        <MaterialIcon name="arrow_forward" size={16} />
      </Link>
    </section>
  );
}
