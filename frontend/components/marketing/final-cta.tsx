"use client";

import { useRouter } from "next/navigation";
import { KovaInput, type KovaIntent } from "@/components/shared/kova-input";

interface FinalCTAProps {
  onSubmit?: (intent: KovaIntent) => void;
}

export function FinalCTA({ onSubmit }: FinalCTAProps) {
  const router = useRouter();

  const handleSubmit = (intent: KovaIntent) => {
    if (onSubmit) {
      onSubmit(intent);
      return;
    }
    const target = intent.url || intent.raw;
    if (target) {
      const query = new URLSearchParams();
      query.set("url", target);
      if (intent.instruction) {
        query.set("intent", intent.instruction);
      }
      router.push(`/explore?${query.toString()}`);
    }
  };

  return (
    <section className="py-24 md:py-36 bg-secondary/35 border-t border-border/80">
      <div className="mx-auto max-w-6xl px-6 text-center">
        <span className="text-label text-muted-foreground mb-3 block">
          Get started
        </span>
        <h2 className="text-h1 md:text-[3rem] md:leading-tight text-foreground mb-4 tracking-tight">
          Give Kova your product.
        </h2>
        <p className="text-body-lg text-muted-foreground mb-10 max-w-lg mx-auto">
          Start with a website. Let the agent take it from there.
        </p>

        <div className="max-w-2xl mx-auto">
          <KovaInput onSubmit={handleSubmit} size="lg" variant="hero" />
        </div>
      </div>
    </section>
  );
}
