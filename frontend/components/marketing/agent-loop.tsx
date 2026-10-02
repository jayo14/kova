"use client";

import { useEffect, useRef, useState } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";

interface LoopStep {
  id: string;
  name: string;
  subtitle: string;
  icon: string;
  inspectionTitle: string;
  stateDescription: string;
  telemetry: Array<{ label: string; value: string }>;
}

const steps: LoopStep[] = [
  {
    id: "observe",
    name: "OBSERVE",
    subtitle: "Read current browser state",
    icon: "visibility",
    inspectionTitle: "Live DOM & Viewport Inspection",
    stateDescription:
      "Kova captures the visual viewport and accessibility tree, identifying interactive elements, inputs, buttons, and system state.",
    telemetry: [
      { label: "Target URL", value: "https://app.studymate.ai/dashboard" },
      { label: "DOM elements parsed", value: "314 interactive targets" },
      { label: "Current view", value: "Material library overview" },
      { label: "Detected state", value: "Authenticated session active" },
    ],
  },
  {
    id: "understand",
    name: "UNDERSTAND",
    subtitle: "Resolve intent against the interface",
    icon: "psychology",
    inspectionTitle: "Goal Resolution & Strategy",
    stateDescription:
      "Kova compares the objective against what is visible, calculating the next logical user step rather than relying on brittle pre-recorded paths.",
    telemetry: [
      { label: "Objective", value: "Generate quiz from uploaded document" },
      { label: "Resolved path", value: "Select 'Biology 101 Notes.pdf' -> Click 'Create Quiz'" },
      { label: "Selector strategy", value: "Semantic button match: [data-action='generate']" },
      { label: "Confidence", value: "High (primary CTA visible)" },
    ],
  },
  {
    id: "act",
    name: "ACT",
    subtitle: "Execute native browser events",
    icon: "touch_app",
    inspectionTitle: "Direct Browser Interaction",
    stateDescription:
      "Kova dispatches human-like interactions: mouse clicks, smooth keyboard input, file uploads, and navigation events.",
    telemetry: [
      { label: "Dispatched action", value: "Click button.primary-cta ('Generate Quiz')" },
      { label: "Input payload", value: "{ questions: 10, difficulty: 'medium' }" },
      { label: "Execution time", value: "142ms native event dispatch" },
      { label: "Network status", value: "POST /api/v1/quizzes -> 201 Created" },
    ],
  },
  {
    id: "verify",
    name: "VERIFY",
    subtitle: "Validate outcome & adapt",
    icon: "verified",
    inspectionTitle: "Outcome Verification & Evidence",
    stateDescription:
      "Kova inspects the post-action interface to ensure the expected state materialized. If an unexpected modal or error appeared, it adapts and recovers.",
    telemetry: [
      { label: "Post-action check", value: "Quiz container rendered in DOM" },
      { label: "Assertion", value: "Text 'Biology 101 Quiz' visible" },
      { label: "Result", value: "PASS (Journey milestone 4 of 4 completed)" },
      { label: "Next cycle", value: "Loop back to OBSERVE for next objective" },
    ],
  },
];

export function AgentLoop() {
  const [activeIndex, setActiveIndex] = useState(0);
  const [isPaused, setIsPaused] = useState(false);
  const sectionRef = useRef<HTMLElement>(null);
  const hasAnimated = useRef(false);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && !hasAnimated.current) {
            hasAnimated.current = true;
          }
        });
      },
      { threshold: 0.2 }
    );

    if (sectionRef.current) {
      observer.observe(sectionRef.current);
    }

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (isPaused) return;

    const interval = setInterval(() => {
      setActiveIndex((prev) => (prev + 1) % steps.length);
    }, 3200);

    return () => clearInterval(interval);
  }, [isPaused]);

  const activeStep = steps[activeIndex];

  return (
    <section
      ref={sectionRef}
      id="agent-loop"
      className="py-24 md:py-32 bg-secondary/35 border-t border-border/70"
    >
      <div className="mx-auto max-w-6xl px-6">
        {/* Section Header */}
        <div className="max-w-2xl mb-16 md:mb-20">
          <span className="text-label text-muted-foreground mb-3 block">
            Autonomous decision loop
          </span>
          <h2 className="text-h1 md:text-[2.75rem] md:leading-tight text-foreground mb-4 tracking-tight">
            It doesn&apos;t just follow a script.
          </h2>
          <p className="text-body-lg text-muted-foreground">
            Kova observes the product, decides what to do, takes an action, checks the result, and adapts when the path changes.
          </p>
        </div>

        {/* The Mechanism Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          {/* Loop Sequence Steps (Left Column) */}
          <div className="lg:col-span-5 flex flex-col gap-2.5">
            {steps.map((step, idx) => {
              const isActive = idx === activeIndex;

              return (
                <div key={step.id} className="relative">
                  <button
                    type="button"
                    onClick={() => {
                      setActiveIndex(idx);
                      setIsPaused(true);
                    }}
                    className={cn(
                      "w-full text-left p-4 rounded-xl border transition-all duration-200 flex items-center justify-between gap-4",
                      isActive
                        ? "border-primary bg-background shadow-xs ring-1 ring-primary"
                        : "border-border/70 bg-background/50 hover:bg-background hover:border-foreground/20"
                    )}
                  >
                    <div className="flex items-center gap-3.5 min-w-0">
                      <div
                        className={cn(
                          "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors",
                          isActive ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground"
                        )}
                      >
                        <MaterialIcon name={step.icon} size={18} />
                      </div>
                      <div className="min-w-0">
                        <span
                          className={cn(
                            "text-label font-bold block",
                            isActive ? "text-primary" : "text-muted-foreground"
                          )}
                        >
                          {step.name}
                        </span>
                        <p className="text-body-sm text-foreground font-medium truncate">
                          {step.subtitle}
                        </p>
                      </div>
                    </div>

                    <MaterialIcon
                      name={isActive ? "play_arrow" : "chevron_right"}
                      size={18}
                      className={cn(
                        "shrink-0 transition-transform",
                        isActive ? "text-primary" : "text-muted-foreground/50"
                      )}
                    />
                  </button>

                  {/* Connecting Arrow */}
                  {idx < steps.length - 1 ? (
                    <div className="h-3 w-px bg-border ml-8 my-0.5" aria-hidden="true" />
                  ) : (
                    <div className="flex items-center gap-2 pl-8 pt-2 text-[0.75rem] text-muted-foreground/70 font-mono">
                      <span>↺ Loops continuously to OBSERVE</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Real-time Telemetry Panel (Right Column) */}
          <div className="lg:col-span-7">
            <div className="rounded-2xl border border-border bg-card shadow-xs overflow-hidden">
              {/* Inspection Header */}
              <div className="flex items-center justify-between border-b border-border bg-secondary/20 px-5 py-3.5">
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-primary animate-pulse" />
                  <span className="text-label text-foreground font-mono">
                    PHASE: {activeStep.name}
                  </span>
                </div>
                <span className="text-caption text-muted-foreground font-mono">
                  Stage {activeIndex + 1} of 4
                </span>
              </div>

              {/* Inspection Content */}
              <div className="p-6 md:p-8 space-y-6">
                <div>
                  <h3 className="text-h3 text-foreground mb-2">
                    {activeStep.inspectionTitle}
                  </h3>
                  <p className="text-body text-muted-foreground leading-relaxed">
                    {activeStep.stateDescription}
                  </p>
                </div>

                {/* Telemetry Key-Values */}
                <div className="rounded-xl border border-border/80 bg-background p-4 space-y-2.5">
                  <p className="text-caption text-muted-foreground uppercase font-mono tracking-wider mb-2">
                    Live Telemetry
                  </p>
                  {activeStep.telemetry.map((item) => (
                    <div
                      key={item.label}
                      className="flex flex-col sm:flex-row sm:items-baseline justify-between text-body-sm gap-1 border-b border-border/30 pb-2 last:border-0 last:pb-0"
                    >
                      <span className="text-muted-foreground font-medium text-caption sm:text-body-sm">
                        {item.label}
                      </span>
                      <span className="font-mono text-foreground text-[0.8125rem] truncate max-w-sm">
                        {item.value}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Progress bar */}
              <div className="h-1 bg-border/40 w-full overflow-hidden">
                <div
                  className="h-full bg-primary transition-all duration-300 ease-out"
                  style={{ width: `${((activeIndex + 1) / steps.length) * 100}%` }}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
