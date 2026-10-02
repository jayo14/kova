"use client";

import { useState, type ReactNode } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import type { QuestionOption } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface AgentQuestionProps {
  title: string;
  description?: string;
  options?: QuestionOption[];
  onSelectOption?: (optionId: string) => void;
  submitLabel?: string;
  loading?: boolean;
  children?: ReactNode;
  className?: string;
}

export function AgentQuestion({
  title,
  description,
  options,
  onSelectOption,
  submitLabel = "Continue",
  loading = false,
  children,
  className,
}: AgentQuestionProps) {
  const [selectedId, setSelectedId] = useState<string>(
    options && options.length > 0 ? options[0].id : ""
  );

  const handleSubmit = () => {
    if (selectedId && onSelectOption) {
      onSelectOption(selectedId);
    }
  };

  return (
    <div className={cn("w-full max-w-lg mx-auto text-center animate-in fade-in zoom-in-95 duration-300", className)}>
      {/* Agent Question Header */}
      <div className="mb-6">
        <div className="inline-flex items-center gap-2 rounded-full border border-border bg-secondary/40 px-3 py-1 text-caption text-muted-foreground mb-4">
          <span className="h-1.5 w-1.5 rounded-full bg-primary" />
          <span>Kova needs your input</span>
        </div>

        <h2 className="text-h2 text-foreground font-semibold mb-2">
          {title}
        </h2>
        {description && (
          <p className="text-body-sm text-muted-foreground max-w-md mx-auto">
            {description}
          </p>
        )}
      </div>

      {/* Option Selection Grid if options provided */}
      {options && options.length > 0 && (
        <div className="space-y-4 mb-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-left">
            {options.map((option) => {
              const isSelected = selectedId === option.id;
              return (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => setSelectedId(option.id)}
                  className={cn(
                    "flex flex-col p-4 rounded-xl border transition-all duration-200 text-left cursor-pointer",
                    isSelected
                      ? "border-primary bg-primary/5 ring-1 ring-primary shadow-xs"
                      : "border-border bg-card hover:border-muted-foreground/30 hover:bg-secondary/20"
                  )}
                >
                  <div className="flex items-center justify-between w-full mb-2">
                    <div className="flex items-center gap-2">
                      {option.icon && (
                        <MaterialIcon
                          name={option.icon}
                          size={18}
                          className={cn(isSelected ? "text-primary" : "text-muted-foreground")}
                        />
                      )}
                      <span className="text-body-sm font-semibold text-foreground">
                        {option.label}
                      </span>
                    </div>

                    <div
                      className={cn(
                        "h-4 w-4 rounded-full border flex items-center justify-center transition-colors",
                        isSelected
                          ? "border-primary bg-primary text-primary-foreground"
                          : "border-muted-foreground/40"
                      )}
                    >
                      {isSelected && <span className="h-1.5 w-1.5 rounded-full bg-background" />}
                    </div>
                  </div>

                  {option.description && (
                    <p className="text-caption text-muted-foreground">
                      {option.description}
                    </p>
                  )}
                </button>
              );
            })}
          </div>

          <div className="flex justify-center pt-2">
            <Button
              onClick={handleSubmit}
              disabled={!selectedId || loading}
              className="px-6"
            >
              {loading ? (
                <MaterialIcon name="progress_activity" size={16} className="animate-spin" />
              ) : (
                <>
                  {submitLabel}
                  <MaterialIcon name="arrow_forward" size={16} />
                </>
              )}
            </Button>
          </div>
        </div>
      )}

      {/* Custom Children Form Container (e.g. Credential Form) */}
      {children && <div className="text-left">{children}</div>}
    </div>
  );
}
