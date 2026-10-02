"use client";

import { useSyncExternalStore, useCallback } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";

type Theme = "system" | "light" | "dark";

function getStoredTheme(): Theme {
  if (typeof window === "undefined") return "system";
  const stored = localStorage.getItem("kova-theme") as Theme | null;
  return stored ?? "system";
}

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "dark") {
    root.classList.add("dark");
  } else if (theme === "light") {
    root.classList.remove("dark");
  } else {
    const prefersDark = window.matchMedia(
      "(prefers-color-scheme: dark)"
    ).matches;
    if (prefersDark) {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }
}

function subscribe(callback: () => void): () => void {
  window.addEventListener("storage", callback);
  return () => window.removeEventListener("storage", callback);
}

export function AppearanceSection() {
  const theme = useSyncExternalStore(
    subscribe,
    getStoredTheme,
    () => "system" as Theme
  );

  const handleThemeChange = useCallback((newTheme: Theme) => {
    localStorage.setItem("kova-theme", newTheme);
    applyTheme(newTheme);
    // Trigger re-render for other components
    window.dispatchEvent(new Event("storage"));
  }, []);

  const options: { value: Theme; label: string; icon: string }[] = [
    { value: "system", label: "System", icon: "computer" },
    { value: "light", label: "Light", icon: "light_mode" },
    { value: "dark", label: "Dark", icon: "dark_mode" },
  ];

  return (
    <div className="rounded-2xl border border-border/70 bg-card/50 p-6 transition-colors">
      <div className="mb-4">
        <h2 className="text-body font-semibold text-foreground">Appearance</h2>
        <p className="text-caption text-muted-foreground">
          Choose how Kova looks on your device.
        </p>
      </div>

      <div
        role="radiogroup"
        aria-label="Theme preference"
        className="flex flex-wrap gap-3 pt-2 border-t border-border/50"
      >
        {options.map((opt) => {
          const isSelected = theme === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={isSelected}
              onClick={() => handleThemeChange(opt.value)}
              className={`flex items-center gap-2.5 rounded-xl border px-4 py-2 text-body-sm transition-all select-none ${
                isSelected
                  ? "border-primary/80 bg-primary/10 text-primary font-medium shadow-2xs ring-1 ring-primary/20"
                  : "border-border/80 bg-card/60 text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
              }`}
            >
              <MaterialIcon
                name={opt.icon}
                size={16}
                className={isSelected ? "text-primary" : "text-muted-foreground"}
              />
              <span>{opt.label}</span>
              {isSelected && (
                <MaterialIcon
                  name="check"
                  size={14}
                  className="text-primary ml-0.5"
                />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
