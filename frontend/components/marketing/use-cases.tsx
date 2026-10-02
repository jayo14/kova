import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";

const useCases = [
  {
    title: "Test",
    headline: "Run real user journeys before your users do.",
    description:
      "Simulate complete end-to-end customer workflows across desktop and mobile viewports, finding regressions before code reaches production.",
    example: "Sign up -> Complete profile -> Connect payment -> Complete first purchase",
    icon: "rule",
  },
  {
    title: "Validate",
    headline: "Turn product requirements into executable journeys.",
    description:
      "Verify that newly deployed features satisfy acceptance criteria. Give Kova the requirement specification and let it confirm the behavior.",
    example: "Verify free-tier accounts cannot access enterprise team invitation settings",
    icon: "task_alt",
  },
  {
    title: "Explore",
    headline: "Let Kova discover how your product actually behaves.",
    description:
      "Point Kova at an unfamiliar surface. The agent catalogs available user paths, documents interactive forms, and highlights unexpected errors.",
    example: "Discover 14 interactive workflows and 3 broken redirect states on staging",
    icon: "explore",
  },
  {
    title: "Demonstrate",
    headline: "Turn real product interactions into repeatable demonstrations.",
    description:
      "Record every action, state transition, and verified result so team members and stakeholders can audit the product in motion.",
    example: "Generate reproducible action logs and verification artifacts for release sign-off",
    icon: "history",
  },
];

export function UseCases() {
  return (
    <section id="product" className="py-24 md:py-32 border-t border-border/80">
      <div className="mx-auto max-w-6xl px-6">
        {/* Section Header */}
        <div className="max-w-2xl mb-16 md:mb-20">
          <span className="text-label text-muted-foreground mb-3 block">
            Capabilities
          </span>
          <h2 className="text-h1 md:text-[2.75rem] md:leading-tight text-foreground tracking-tight">
            One agent. Many jobs.
          </h2>
        </div>

        {/* Large Editorial Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          {useCases.map((uc, idx) => (
            <div
              key={uc.title}
              className={cn(
                "rounded-2xl border border-border bg-card p-8 md:p-10 flex flex-col justify-between transition-all duration-200 hover:border-foreground/30 hover:bg-secondary/15"
              )}
            >
              <div>
                <div className="flex items-center justify-between mb-8">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-secondary text-primary">
                      <MaterialIcon name={uc.icon} size={20} />
                    </div>
                    <span className="text-h3 text-foreground font-bold">
                      {uc.title}
                    </span>
                  </div>
                  <span className="text-mono text-caption text-muted-foreground">
                    Job 0{idx + 1}
                  </span>
                </div>

                <h3 className="text-h3 text-foreground mb-3 leading-snug">
                  {uc.headline}
                </h3>
                <p className="text-body text-muted-foreground leading-relaxed">
                  {uc.description}
                </p>
              </div>

              <div className="mt-8 pt-6 border-t border-border/60">
                <span className="text-caption text-muted-foreground uppercase font-mono block mb-1">
                  Example journey
                </span>
                <p className="font-mono text-body-sm text-foreground/90">
                  {uc.example}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
