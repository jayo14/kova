"use client";

import { useState, useEffect, useRef, type ChangeEvent, type KeyboardEvent } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { parseIntent, type KovaIntent } from "@/components/shared/kova-input";
import { cn } from "@/lib/utils";

export interface KovaCommandInputProps {
  variant?: "landing" | "dashboard";
  onSubmit: (intent: KovaIntent) => void;
  loading?: boolean;
  disabled?: boolean;
  autoFocus?: boolean;
  placeholder?: string;
  placeholders?: string[];
  className?: string;
}

const dashboardPlaceholders = [
  "Give Kova a website or a job...",
  "https://your-product.com",
  "Test whether a student can generate a quiz",
  "https://quiza.app — test quiz generation",
  "Show me how a new user signs up",
  "Verify that checkout works",
];

export function KovaCommandInput({
  variant = "dashboard",
  onSubmit,
  loading = false,
  disabled = false,
  autoFocus = false,
  placeholder,
  placeholders,
  className,
}: KovaCommandInputProps) {
  const [value, setValue] = useState("");
  const [placeholderIndex, setPlaceholderIndex] = useState(0);
  const [isFocused, setIsFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const activePlaceholders = placeholders ?? (placeholder ? [placeholder] : dashboardPlaceholders);

  // Subtle rotation of example placeholders every 4.5 seconds when input is empty & unfocused
  useEffect(() => {
    if (value || isFocused || activePlaceholders.length <= 1) return;
    const interval = setInterval(() => {
      setPlaceholderIndex((prev) => (prev + 1) % activePlaceholders.length);
    }, 4500);
    return () => clearInterval(interval);
  }, [value, isFocused, activePlaceholders.length]);

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || loading || disabled) return;

    const parsed = parseIntent(trimmed);
    onSubmit(parsed);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const activePlaceholder = activePlaceholders[placeholderIndex % activePlaceholders.length];

  return (
    <form
      onSubmit={handleSubmit}
      className={cn(
        "group relative flex w-full items-center rounded-2xl border ring-0 ring-primary/20 transition-all duration-300 ease-in-out",
        variant === "dashboard"
          ? "bg-card/90 border-border/90 shadow-sm hover:border-muted-foreground/40 focus-within:border-transparent focus-within:ring-[3px]"
          : "bg-background border-border shadow-xs hover:border-muted-foreground/30 focus-within:border-transparent focus-within:ring-2",
        className
      )}
    >
      <div className="flex h-12 w-12 shrink-0 items-center justify-center text-muted-foreground">
        <MaterialIcon
          name="auto_awesome"
          size={18}
          className={cn(
            "transition-colors",
            isFocused ? "text-primary" : "text-muted-foreground/60"
          )}
        />
      </div>

      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e: ChangeEvent<HTMLInputElement>) => setValue(e.target.value)}
        onFocus={() => setIsFocused(true)}
        onBlur={() => setIsFocused(false)}
        onKeyDown={handleKeyDown}
        placeholder={activePlaceholder}
        disabled={disabled || loading}
        autoFocus={autoFocus}
        className="flex-1 bg-transparent py-3 pr-2 text-body font-sans text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus-visible:outline-none focus:ring-0 focus:border-transparent disabled:opacity-50"
        aria-label="What should Kova work on?"
      />

      <div className="pr-2">
        <Button
          type="submit"
          disabled={!value.trim() || loading || disabled}
          size="sm"
          className="h-8 w-8 rounded-xl p-0 font-medium shrink-0"
          aria-label="Submit command to Kova"
        >
          {loading ? (
            <MaterialIcon name="progress_activity" size={16} className="animate-spin" />
          ) : (
            <MaterialIcon name="arrow_forward" size={16} />
          )}
        </Button>
      </div>
    </form>
  );
}
