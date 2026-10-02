import { MaterialIcon } from "@/components/shared/material-icon";

const traditionalScript = [
  { step: "01", instruction: "Click button#submit-btn", note: "Hardcoded CSS selector" },
  { step: "02", instruction: "Type input[name='email'] 'test@domain.com'", note: "Brittle DOM path" },
  { step: "03", instruction: "Click div.nav-item > a:nth-child(2)", note: "Breaks on layout reorder" },
  { step: "04", instruction: "Expect element #modal-confirm to exist", note: "Fails if wording updates" },
];

const kovaSteps = [
  {
    name: "Goal",
    description: "Start with what the user actually wants to accomplish",
    icon: "flag",
  },
  {
    name: "Understand",
    description: "Analyze the current screen structure and accessibility tree",
    icon: "psychology",
  },
  {
    name: "Choose",
    description: "Select the next best action toward the objective",
    icon: "account_tree",
  },
  {
    name: "Act",
    description: "Dispatch native browser interactions as a real user",
    icon: "touch_app",
  },
  {
    name: "Verify",
    description: "Confirm the intended outcome occurred, adapting if blocked",
    icon: "verified",
  },
];

export function AgenticSection() {
  return (
    <section className="py-24 md:py-32 bg-secondary/30 border-t border-border/70">
      <div className="mx-auto max-w-6xl px-6">
        {/* Section Header */}
        <div className="max-w-2xl mb-16 md:mb-20">
          <span className="text-label text-muted-foreground mb-3 block">
            Philosophy
          </span>
          <h2 className="text-h1 md:text-[2.75rem] md:leading-tight text-foreground mb-4 tracking-tight">
            You don&apos;t have to script every click.
          </h2>
          <p className="text-body-lg text-muted-foreground">
            Traditional automation tells software exactly what to click. Kova starts with an objective and works out the path.
          </p>
        </div>

        {/* Side-by-Side Comparison */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-stretch">
          {/* Traditional Automation Column */}
          <div className="rounded-2xl border border-border bg-card p-8 md:p-10 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between pb-6 mb-6 border-b border-border/70">
                <span className="text-label text-muted-foreground font-mono">
                  Traditional automation
                </span>
                <span className="text-caption text-muted-foreground font-mono">
                  Fragile scripting
                </span>
              </div>

              <p className="text-body-sm text-muted-foreground mb-6">
                Requires manual authoring and continuous maintenance whenever CSS classes, layout structure, or component hierarchies change.
              </p>

              <div className="space-y-3 font-mono text-body-sm">
                {traditionalScript.map((line) => (
                  <div
                    key={line.step}
                    className="p-3 rounded-lg bg-background/80 border border-border/60 flex items-start gap-3"
                  >
                    <span className="text-caption text-muted-foreground shrink-0 mt-0.5">
                      {line.step}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-foreground/90 truncate text-[0.8125rem]">
                        {line.instruction}
                      </p>
                      <p className="text-[0.6875rem] text-muted-foreground/80 mt-0.5">
                        {line.note}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-8 pt-6 border-t border-border/60">
              <p className="text-caption text-muted-foreground flex items-center gap-1.5">
                <MaterialIcon name="warning" size={15} className="text-muted-foreground shrink-0" />
                Breaks when the interface changes.
              </p>
            </div>
          </div>

          {/* Kova Column */}
          <div className="rounded-2xl border border-primary/30 bg-background p-8 md:p-10 flex flex-col justify-between shadow-xs">
            <div>
              <div className="flex items-center justify-between pb-6 mb-6 border-b border-border/70">
                <span className="text-label text-primary font-bold">
                  Kova
                </span>
                <span className="text-caption text-primary font-mono">
                  Autonomous journey
                </span>
              </div>

              <p className="text-body-sm text-foreground/80 mb-6">
                Understands the intent of the product journey. Navigates, adapts, and recovers when modals appear, buttons move, or flows shift.
              </p>

              <div className="space-y-3">
                {kovaSteps.map((step, idx) => (
                  <div
                    key={step.name}
                    className="p-3 rounded-lg border border-border/70 bg-card/60 flex items-start gap-3 transition-colors hover:border-primary/40"
                  >
                    <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary shrink-0 mt-0.5">
                      <MaterialIcon name={step.icon} size={15} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-body-sm font-semibold text-foreground">
                          {step.name}
                        </span>
                        {idx < kovaSteps.length - 1 && (
                          <span className="text-caption text-muted-foreground font-mono">
                            →
                          </span>
                        )}
                      </div>
                      <p className="text-caption text-muted-foreground mt-0.5">
                        {step.description}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-8 pt-6 border-t border-border/60">
              <p className="text-caption text-primary font-medium flex items-center gap-1.5">
                <MaterialIcon name="check_circle" size={15} className="text-primary shrink-0" />
                Adapts when the path changes.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
