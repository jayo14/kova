import { MaterialIcon } from "@/components/shared/material-icon";

export function DashboardEmptyState() {
  return (
    <section
      aria-label="Workspace overview"
      className="rounded-2xl border border-border/80 bg-secondary/15 px-6 py-12 text-center"
    >
      <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-primary/5 text-primary">
        <MaterialIcon
          name="explore"
          size={20}
          className="text-primary/70"
        />
      </div>
      <h3 className="text-body font-semibold text-foreground mb-1.5">
        Your workspace is empty.
      </h3>
      <p className="text-body-sm text-muted-foreground max-w-sm mx-auto leading-relaxed">
        Give Kova a website or a job above. It&apos;ll explore the product,
        find useful journeys, and help you decide what to run.
      </p>
    </section>
  );
}
