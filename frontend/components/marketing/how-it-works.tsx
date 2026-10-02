import { cn } from "@/lib/utils";

const stages = [
  {
    step: "01",
    title: "Give it a product",
    description: "Your website becomes Kova's environment.",
    detail: "Provide a public URL, staging link, or protected application endpoint.",
  },
  {
    step: "02",
    title: "Let it understand",
    description: "Kova explores the interface and discovers how a real user can move through it.",
    detail: "Observes elements, interactive forms, navigation links, and permissions.",
  },
  {
    step: "03",
    title: "Let it act",
    description: "Kova navigates, clicks, types, uploads, and completes the journey.",
    detail: "Executes real browser interactions directly against the live DOM.",
  },
  {
    step: "04",
    title: "Get proof",
    description: "Kova verifies what happened and records the evidence.",
    detail: "Produces screenshots, action logs, timing data, and cryptographic artifacts.",
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="py-24 md:py-32 border-t border-border/80">
      <div className="mx-auto max-w-6xl px-6">
        {/* Section Header */}
        <div className="max-w-2xl mb-16 md:mb-20">
          <span className="text-label text-muted-foreground mb-3 block">
            How it works
          </span>
          <h2 className="text-h1 md:text-[2.75rem] md:leading-tight text-foreground tracking-tight">
            Give Kova the job.
          </h2>
        </div>

        {/* Progressive Editorial Stages */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8 lg:gap-0 lg:divide-x lg:divide-border border-y lg:border lg:border-border rounded-2xl bg-card overflow-hidden">
          {stages.map((stage, idx) => (
            <div
              key={stage.step}
              className={cn(
                "p-8 lg:p-9 flex flex-col justify-between group transition-colors duration-200 hover:bg-secondary/25",
                idx > 0 && "border-t md:border-t-0 border-border/70"
              )}
            >
              <div>
                <span className="text-mono text-body-sm font-semibold text-primary block mb-6">
                  {stage.step}
                </span>
                <h3 className="text-h3 text-foreground mb-3 leading-snug">
                  {stage.title}
                </h3>
                <p className="text-body text-muted-foreground leading-relaxed">
                  {stage.description}
                </p>
              </div>

              <div className="mt-8 pt-6 border-t border-border/40">
                <p className="text-caption text-muted-foreground/80 leading-normal">
                  {stage.detail}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
