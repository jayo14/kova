import React from "react";
import { cn } from "@/lib/utils";
import type { ValidationMode } from "@/lib/types";

export function getValidationModeConfig(mode?: ValidationMode | string | null) {
  const normalized = (mode || "functional").toLowerCase();
  switch (normalized) {
    case "workflow":
      return {
        label: "Workflow",
        badgeClass: "bg-purple-500/10 text-purple-700 dark:text-purple-300 border-purple-500/20 border",
        dotClass: "bg-purple-500",
      };
    case "regression":
      return {
        label: "Regression",
        badgeClass: "bg-neutral-500/10 text-neutral-700 dark:text-neutral-300 border-neutral-500/20 border",
        dotClass: "bg-neutral-500",
      };
    case "exploratory":
      return {
        label: "Exploratory",
        badgeClass: "bg-orange-500/10 text-orange-700 dark:text-orange-300 border-orange-500/20 border",
        dotClass: "bg-orange-500",
      };
    case "visual":
      return {
        label: "Visual",
        badgeClass: "bg-pink-500/10 text-pink-700 dark:text-pink-300 border-pink-500/20 border",
        dotClass: "bg-pink-500",
      };
    case "functional":
    default:
      return {
        label: "Functional",
        badgeClass: "bg-blue-500/10 text-blue-700 dark:text-blue-300 border-blue-500/20 border",
        dotClass: "bg-blue-500",
      };
  }
}

interface ModeBadgeProps {
  mode?: ValidationMode | string | null;
  className?: string;
}

export function ModeBadge({ mode, className }: ModeBadgeProps) {
  const config = getValidationModeConfig(mode);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-caption font-medium px-2 py-0.5 rounded-md capitalize",
        config.badgeClass,
        className
      )}
      data-testid="validation-mode-badge"
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", config.dotClass)} />
      <span>{config.label}</span>
    </span>
  );
}
