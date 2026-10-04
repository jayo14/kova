"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { MaterialIcon } from "@/components/shared/material-icon";
import { buttonVariants, Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function ProjectEmptyState() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  const handleTryDemo = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/v1/projects/demo", { credentials: "include", method: "POST" });
      if (res.ok) {
        const project = await res.json();
        router.push(`/projects/${project.id}`);
      } else {
        router.push("/explore");
      }
    } catch {
      router.push("/explore");
    } finally {
      setLoading(false);
    }
  };

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
        Give Kova a website and let it explore, or launch the interactive demo to see Kova detect planted UI and network bugs.
      </p>
      <div className="flex flex-wrap items-center justify-center gap-3">
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
        <Button
          variant="outline"
          onClick={handleTryDemo}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-body-sm font-medium shadow-sm transition-all"
        >
          <MaterialIcon name="play_circle" size={16} />
          <span>{loading ? "Setting up..." : "Try the demo"}</span>
        </Button>
      </div>
    </section>
  );
}

