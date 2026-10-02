"use client";

import { useState, useEffect, useCallback } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";
import type { ScreenshotEntry } from "@/components/explore/explore-state-machine";

interface ScreenshotGalleryProps {
  screenshots: ScreenshotEntry[];
  initialIndex?: number;
  open: boolean;
  onClose: () => void;
}

export function ScreenshotGallery({
  screenshots,
  initialIndex = 0,
  open,
  onClose,
}: ScreenshotGalleryProps) {
  const [currentIndex, setCurrentIndex] = useState(initialIndex);

  useEffect(() => {
    setCurrentIndex(initialIndex);
  }, [initialIndex, open]);

  const goNext = useCallback(() => {
    setCurrentIndex((i) => (i + 1) % screenshots.length);
  }, [screenshots.length]);

  const goPrev = useCallback(() => {
    setCurrentIndex((i) => (i - 1 + screenshots.length) % screenshots.length);
  }, [screenshots.length]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") goNext();
      else if (e.key === "ArrowLeft") goPrev();
      else if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, goNext, goPrev, onClose]);

  if (!open || screenshots.length === 0) return null;

  const current = screenshots[currentIndex];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative flex flex-col items-center max-w-4xl w-full mx-4">
        {/* Header */}
        <div className="flex items-center justify-between w-full mb-3">
          <div className="flex items-center gap-2">
            <MaterialIcon name="photo_library" size={18} className="text-muted-foreground" />
            <span className="text-body-sm font-medium text-foreground">
              Screenshot {currentIndex + 1} of {screenshots.length}
            </span>
            {current.label && (
              <span className="text-caption text-muted-foreground">— {current.label}</span>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-colors"
          >
            <MaterialIcon name="close" size={18} />
          </button>
        </div>

        {/* Image */}
        <div className="relative flex-1 w-full rounded-xl overflow-hidden border border-border bg-black">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={current.url}
            alt={`Screenshot ${currentIndex + 1}`}
            className="w-full h-auto max-h-[70vh] object-contain"
          />

          {/* Nav arrows */}
          {screenshots.length > 1 && (
            <>
              <button
                onClick={goPrev}
                className="absolute left-3 top-1/2 -translate-y-1/2 p-2 rounded-full bg-black/50 hover:bg-black/70 text-white transition-colors"
              >
                <MaterialIcon name="chevron_left" size={24} />
              </button>
              <button
                onClick={goNext}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-2 rounded-full bg-black/50 hover:bg-black/70 text-white transition-colors"
              >
                <MaterialIcon name="chevron_right" size={24} />
              </button>
            </>
          )}
        </div>

        {/* Thumbnail strip */}
        {screenshots.length > 1 && (
          <div className="flex gap-2 mt-3 overflow-x-auto pb-1">
            {screenshots.map((s, i) => (
              <button
                key={s.id}
                onClick={() => setCurrentIndex(i)}
                className={cn(
                  "shrink-0 w-16 h-12 rounded-lg overflow-hidden border-2 transition-all",
                  i === currentIndex
                    ? "border-primary ring-2 ring-primary/20"
                    : "border-border opacity-60 hover:opacity-100"
                )}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={s.url}
                  alt={`Thumbnail ${i + 1}`}
                  className="w-full h-full object-cover"
                />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
