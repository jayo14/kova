"use client";

import { useRouter } from "next/navigation";
import { KovaInput, type KovaIntent } from "@/components/shared/kova-input";
import { MaterialIcon } from "@/components/shared/material-icon";

export function Hero() {
  const router = useRouter();

  const handleSubmit = (intent: KovaIntent) => {
    const target = intent.url || intent.raw;
    if (target) {
      const query = new URLSearchParams();
      query.set("url", target);
      const goal = intent.goal || intent.instruction;
      if (goal) {
        query.set("intent", goal);
      }
      router.push(`/explore?${query.toString()}`);
    }
  };

  return (
    <section id="hero" className="relative overflow-hidden pt-20 pb-20 md:pt-28 md:pb-28">
      <div className="mx-auto max-w-6xl px-6">
        <div className="flex flex-col items-center text-center">
            {/* Editorial Eyebrow */}
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-border bg-secondary/40 text-caption font-medium text-muted-foreground mb-8">
              <span className="h-1.5 w-1.5 rounded-full bg-primary" />
              <span>Autonomous software-use agent</span>
            </div>

            {/* Headline */}
            <h1 className="text-display sm:text-[4.25rem] md:text-[4.75rem] md:leading-[1.04] text-foreground mb-6 max-w-3xl tracking-tight">
              Let an agent use your software.
            </h1>

            {/* Supporting Subtitle */}
            <p className="text-body-lg md:text-[1.25rem] md:leading-relaxed text-muted-foreground mb-10 max-w-xl">
              Give Kova a website and a goal. It explores the product, figures out what needs to happen, and executes the journey like a real user.
            </p>

            {/* Universal Command Input */}
            <div className="w-full max-w-2xl mb-4">
              <KovaInput onSubmit={handleSubmit} size="lg" variant="hero" autoFocus />
            </div>

            <p className="text-caption text-muted-foreground mb-16 max-w-md">
              Enter your product URL or describe what you want Kova to do
            </p>

            {/* Product Visualization Viewport Fallback */}
            <div className="w-full max-w-3xl text-left">
              <div className="rounded-2xl border border-border bg-card shadow-xs overflow-hidden transition-all duration-300">
                {/* Browser Frame Header */}
                <div className="flex items-center justify-between border-b border-border bg-secondary/30 px-4 py-3">
                  <div className="flex items-center gap-1.5" aria-hidden="true">
                    <span className="h-3 w-3 rounded-full bg-border" />
                    <span className="h-3 w-3 rounded-full bg-border" />
                    <span className="h-3 w-3 rounded-full bg-border" />
                  </div>

                  <div className="flex items-center gap-2 rounded-md bg-background px-3 py-1 border border-border/80 max-w-xs w-full justify-center">
                    <MaterialIcon name="lock" size={13} className="text-muted-foreground" />
                    <span className="text-mono text-[0.8125rem] text-foreground truncate">
                      https://app.studymate.ai
                    </span>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <span className="inline-flex items-center gap-1 text-[0.75rem] font-medium px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                      <MaterialIcon name="check" size={12} />
                      Verified
                    </span>
                  </div>
                </div>

                {/* Viewport Interior with Real Execution Preview */}
                <div className="p-6 md:p-8 space-y-6">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border/60 pb-4">
                    <div>
                      <span className="text-label text-muted-foreground">Sample verified execution</span>
                      <p className="text-body font-semibold text-foreground mt-0.5">
                        Generate quiz from study materials
                      </p>
                    </div>
                    <div className="flex items-center gap-3 text-caption text-muted-foreground font-mono">
                      <span>42s duration</span>
                      <span>•</span>
                      <span>6 actions</span>
                      <span>•</span>
                      <span className="text-primary font-medium">1 verification</span>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div className="flex items-center gap-3 p-3 rounded-xl border border-border/60 bg-background/50">
                      <MaterialIcon name="check_circle" size={18} className="text-primary shrink-0" />
                      <span className="text-body-sm text-foreground">Opened application &amp; explored navigation</span>
                    </div>
                    <div className="flex items-center gap-3 p-3 rounded-xl border border-border/60 bg-background/50">
                      <MaterialIcon name="check_circle" size={18} className="text-primary shrink-0" />
                      <span className="text-body-sm text-foreground">Signed in with test credentials</span>
                    </div>
                    <div className="flex items-center gap-3 p-3 rounded-xl border border-border/60 bg-background/50">
                      <MaterialIcon name="check_circle" size={18} className="text-primary shrink-0" />
                      <span className="text-body-sm text-foreground">Uploaded biology study guide document</span>
                    </div>
                    <div className="flex items-center gap-3 p-3 rounded-xl border border-border/60 bg-background/50">
                      <MaterialIcon name="check_circle" size={18} className="text-primary shrink-0" />
                      <span className="text-body-sm text-foreground">Generated 10-question quiz &amp; verified result</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
      </div>
    </section>
  );
}
