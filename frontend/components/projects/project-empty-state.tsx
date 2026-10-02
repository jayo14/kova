import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function ProjectEmptyState() {
  return (
    <section
      aria-label="No projects"
      className="rounded-2xl border border-border/80 bg-secondary/15 px-6 py-14 text-center"
    >
      <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-primary/5 text-primary">
        <MaterialIcon
          name="explore"
          size={22}
          className="text-primary/70"
        />
      </div>
      <h3 className="text-body font-semibold text-foreground mb-1.5">
        No products yet
      </h3>
      <p className="text-body-sm text-muted-foreground max-w-sm mx-auto mb-5 leading-relaxed">
        Give Kova a website and let it explore. Kova will map user journeys and establish your product context.
      </p>
      <Link
        href="/explore"
        className={cn(
          buttonVariants({ variant: "default" }),
          "inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-body-sm font-medium shadow-sm transition-all"
        )}
      >
        <span>Give Kova a product</span>
        <MaterialIcon name="arrow_forward" size={16} />
      </Link>
    </section>
  );
}
