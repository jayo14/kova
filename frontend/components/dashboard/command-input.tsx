"use client";

import { useRouter } from "next/navigation";
import { KovaCommandInput } from "@/components/agent/kova-command-input";
import { MaterialIcon } from "@/components/shared/material-icon";
import type { KovaIntent } from "@/components/shared/kova-input";

export function DashboardCommandInput() {
  const router = useRouter();

  const handleSubmit = (intent: KovaIntent) => {
    const params = new URLSearchParams();
    if (intent.url) {
      params.set("url", intent.url);
    }
    const goal = intent.goal || intent.instruction;
    if (goal) {
      params.set("intent", goal);
    }
    router.push(`/explore?${params.toString()}`);
  };

  return (
    <div className="w-full max-w-xl mx-auto flex flex-col items-center">
      <KovaCommandInput
        variant="dashboard"
        onSubmit={handleSubmit}
        autoFocus
      />

      {/* Lightweight Quick Actions */}
      <div className="flex flex-wrap items-center justify-center gap-2 mt-4 text-caption text-muted-foreground select-none">
        <button
          type="button"
          onClick={() => router.push("/explore")}
          className="inline-flex items-center gap-1.5 rounded-full border border-border/80 bg-secondary/30 px-3 py-1 hover:bg-secondary/60 hover:text-foreground transition-colors cursor-pointer"
        >
          <MaterialIcon name="explore" size={13} className="text-primary" />
          <span>Explore a product</span>
        </button>

        <button
          type="button"
          onClick={() => router.push("/executions")}
          className="inline-flex items-center gap-1.5 rounded-full border border-border/80 bg-secondary/30 px-3 py-1 hover:bg-secondary/60 hover:text-foreground transition-colors cursor-pointer"
        >
          <MaterialIcon name="play_circle" size={13} className="text-muted-foreground" />
          <span>View recent executions</span>
        </button>
      </div>
    </div>
  );
}
