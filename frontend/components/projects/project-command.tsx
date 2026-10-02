"use client";

import { useRouter } from "next/navigation";
import { KovaCommandInput } from "@/components/agent/kova-command-input";
import { MaterialIcon } from "@/components/shared/material-icon";
import type { KovaIntent } from "@/components/shared/kova-input";

interface ProjectCommandInputProps {
  projectName: string;
  projectId: string;
  baseUrl: string;
}

export function ProjectCommandInput({
  projectName,
  projectId,
  baseUrl,
}: ProjectCommandInputProps) {
  const router = useRouter();

  const handleCommand = (instruction: string) => {
    const params = new URLSearchParams();
    params.set("projectId", projectId);
    params.set("url", baseUrl);
    if (instruction.trim()) {
      params.set("intent", instruction.trim());
    }
    router.push(`/explore?${params.toString()}`);
  };

  const handleSubmit = (intent: KovaIntent) => {
    const instruction = intent.instruction || intent.raw || "";
    handleCommand(instruction);
  };

  const suggestions = [
    "Test signup flow",
    "Explore checkout journey",
    "Check mobile responsiveness",
  ];

  return (
    <div className="w-full">
      <div className="mb-2">
        <label className="text-body-sm font-medium text-foreground">
          What should Kova do with {projectName}?
        </label>
      </div>

      <KovaCommandInput
        variant="dashboard"
        placeholder={`What should Kova do with ${projectName}?`}
        onSubmit={handleSubmit}
      />

      <div className="flex flex-wrap items-center gap-2 mt-3 text-caption text-muted-foreground select-none">
        <span className="text-muted-foreground/60">Suggestions:</span>
        {suggestions.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            onClick={() => handleCommand(suggestion)}
            className="inline-flex items-center gap-1 rounded-full border border-border/70 bg-secondary/20 px-2.5 py-0.5 text-body-xs hover:bg-secondary/50 hover:text-foreground transition-colors cursor-pointer"
          >
            <MaterialIcon name="auto_awesome" size={12} className="text-primary/70" />
            <span>{suggestion}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
