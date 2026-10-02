"use client";

import { useState, useRef, useEffect, type KeyboardEvent, type ChangeEvent } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { parseKovaInput, type KovaIntent } from "@/lib/agent/input-parser";

export type { KovaIntent };

export function parseIntent(value: string): KovaIntent {
  return parseKovaInput(value);
}

export interface KovaInputProps {
  value?: string;
  onChange?: (value: string) => void;
  onSubmit?: (intent: KovaIntent) => void;
  placeholder?: string;
  loading?: boolean;
  disabled?: boolean;
  error?: string;
  variant?: "default" | "hero" | "compact";
  size?: "default" | "lg";
  autoFocus?: boolean;
  className?: string;
}

const defaultPlaceholders = [
  "Enter your website URL",
  "https://yourproduct.com",
  "Test whether a user can sign up",
  "Show me how a student generates a quiz",
];

export function KovaInput({
  value: controlledValue,
  onChange: controlledOnChange,
  onSubmit,
  placeholder,
  loading = false,
  disabled = false,
  error,
  variant = "default",
  size = "default",
  autoFocus = false,
  className,
}: KovaInputProps) {
  const [internalValue, setInternalValue] = useState("");
  const [placeholderIndex, setPlaceholderIndex] = useState(0);
  const [isFocused, setIsFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const isControlled = controlledValue !== undefined;
  const currentValue = isControlled ? controlledValue : internalValue;

  const placeholders = placeholder ? [placeholder] : defaultPlaceholders;

  useEffect(() => {
    if (isFocused || currentValue || placeholders.length <= 1) return;
    const interval = setInterval(() => {
      setPlaceholderIndex((i) => (i + 1) % placeholders.length);
    }, 3200);
    return () => clearInterval(interval);
  }, [isFocused, currentValue, placeholders.length]);

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    if (!isControlled) {
      setInternalValue(val);
    }
    controlledOnChange?.(val);
  };

  const handleSubmit = () => {
    const trimmed = currentValue.trim();
    if (!trimmed || loading || disabled) return;
    onSubmit?.(parseIntent(trimmed));
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    }
  };

  const isHero = variant === "hero" || size === "lg";

  return (
    <div className={cn("w-full", className)}>
      <div
        className={cn(
          "group relative flex items-center rounded-xl border bg-background ring-0 ring-primary/20 transition-all duration-300 ease-in-out",
          isHero ? "h-14 sm:h-16 px-3.5" : "h-11 px-2.5",
          error
            ? "border-destructive ring-3 ring-destructive/15"
            : "border-input hover:border-foreground/30 focus-within:border-transparent focus-within:ring-[3px]",
          disabled && "opacity-50 pointer-events-none"
        )}
      >
        <MaterialIcon
          name="language"
          size={isHero ? 22 : 18}
          className={cn(
            "shrink-0 transition-colors duration-200",
            isFocused ? "text-primary" : "text-muted-foreground"
          )}
        />
        <input
          ref={inputRef}
          type="text"
          value={currentValue}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          placeholder={placeholders[placeholderIndex]}
          disabled={disabled}
          autoFocus={autoFocus}
          aria-label="Enter website URL or mission objective"
          className={cn(
            "flex-1 bg-transparent px-3 text-foreground outline-none focus-visible:outline-none focus:ring-0 focus:border-transparent placeholder:text-muted-foreground/70 font-sans tracking-tight",
            isHero ? "text-body-lg sm:text-[1.125rem]" : "text-body"
          )}
        />
        <Button
          type="button"
          onClick={handleSubmit}
          disabled={!currentValue.trim() || loading || disabled}
          size={isHero ? "lg" : "default"}
          className={cn(
            "shrink-0 transition-all duration-200",
            isHero && "h-10 sm:h-11 px-4 sm:px-5 rounded-lg font-medium"
          )}
          aria-label="Run Kova exploration"
        >
          {loading ? (
            <MaterialIcon
              name="progress_activity"
              size={isHero ? 20 : 18}
              className="animate-spin"
            />
          ) : (
            <div className="flex items-center gap-1.5">
              <span className="hidden sm:inline text-body-sm font-medium">Explore</span>
              <MaterialIcon name="arrow_forward" size={isHero ? 18 : 16} />
            </div>
          )}
        </Button>
      </div>

      {error && (
        <p className="mt-1.5 text-caption text-destructive flex items-center gap-1 px-1">
          <MaterialIcon name="error" size={14} />
          {error}
        </p>
      )}
    </div>
  );
}
