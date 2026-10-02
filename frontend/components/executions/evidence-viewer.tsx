"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { cn } from "@/lib/utils";
import type { Evidence } from "@/lib/api/evidence";

interface EvidenceViewerProps {
  evidence: Evidence | null;
  open: boolean;
  onClose: () => void;
  onRefreshUrl?: (evidenceId: string) => Promise<string | null>;
}

export function EvidenceViewer({ evidence, open, onClose, onRefreshUrl }: EvidenceViewerProps) {
  const [imgLoaded, setImgLoaded] = useState(false);
  const [imgError, setImgError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [currentUrl, setCurrentUrl] = useState<string | null>(null);
  const retriedRef = useRef(false);

  useEffect(() => {
    if (open && evidence) {
      setImgLoaded(false);
      setImgError(false);
      setRefreshing(false);
      setCurrentUrl(evidence.url || null);
      retriedRef.current = false;
    }
  }, [open, evidence?.id, evidence?.url]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose]
  );

  useEffect(() => {
    if (!open) return;
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, handleKeyDown]);

  const handleImageError = useCallback(async () => {
    if (retriedRef.current || !onRefreshUrl || !evidence) {
      setImgError(true);
      return;
    }

    retriedRef.current = true;
    setRefreshing(true);

    try {
      const freshUrl = await onRefreshUrl(evidence.id);
      if (freshUrl) {
        setCurrentUrl(freshUrl);
        setImgError(false);
        setRefreshing(false);
        return;
      }
    } catch {
      // refresh failed
    }

    setRefreshing(false);
    setImgError(true);
  }, [onRefreshUrl, evidence]);

  if (!open || !evidence) return null;

  const isImage = evidence.type === "SCREENSHOT" && currentUrl;
  const isVerification = evidence.type === "VERIFICATION";

  const checks = Array.isArray(evidence.metadata?.checks)
    ? (evidence.metadata.checks as Array<{ type: string; passed: boolean; message?: string }>)
    : [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative flex flex-col items-center max-w-3xl w-full mx-4">
        {/* Header */}
        <div className="flex items-center justify-between w-full mb-3">
          <div className="flex items-center gap-2">
            <MaterialIcon
              name={isVerification ? "verified" : "photo_library"}
              size={18}
              className="text-muted-foreground"
            />
            <span className="text-body-sm font-medium text-foreground">
              {evidence.title}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-colors"
          >
            <MaterialIcon name="close" size={18} />
          </button>
        </div>

        {/* Content */}
        {isImage ? (
          <div className="relative w-full rounded-xl overflow-hidden border border-border bg-black">
            {imgError ? (
              <div className="flex flex-col items-center justify-center py-16 text-foreground">
                <MaterialIcon name="broken_image" size={48} className="mb-3 opacity-60" />
                <p className="text-body-sm font-medium">Evidence could not be loaded.</p>
                <p className="text-caption text-muted-foreground mt-1">The signed URL may have expired.</p>
                {onRefreshUrl && (
                  <button
                    onClick={async () => {
                      retriedRef.current = false;
                      setImgError(false);
                      setRefreshing(true);
                      try {
                        const freshUrl = await onRefreshUrl(evidence.id);
                        if (freshUrl) {
                          setCurrentUrl(freshUrl);
                          retriedRef.current = true;
                        } else {
                          setImgError(true);
                        }
                      } catch {
                        setImgError(true);
                      }
                      setRefreshing(false);
                    }}
                    className="mt-3 text-caption text-primary hover:underline"
                    disabled={refreshing}
                  >
                    {refreshing ? "Refreshing..." : "Try again"}
                  </button>
                )}
              </div>
            ) : (
              <>
                {(refreshing || !imgLoaded) && (
                  <div className="flex items-center justify-center py-16">
                    <MaterialIcon name="progress_activity" size={24} className="animate-spin text-muted-foreground" />
                  </div>
                )}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={currentUrl!}
                  alt={evidence.title}
                  className={cn(
                    "w-full h-auto max-h-[70vh] object-contain",
                    !imgLoaded && "hidden"
                  )}
                  onLoad={() => setImgLoaded(true)}
                  onError={handleImageError}
                />
              </>
            )}
          </div>
        ) : isVerification ? (
          <div className="w-full rounded-xl border border-border bg-card p-6">
            <div className="flex items-start gap-3 mb-4">
              <div className="h-10 w-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center shrink-0">
                <MaterialIcon name="check_circle" size={20} className="text-emerald-600" />
              </div>
              <div>
                <p className="text-body-sm font-semibold text-foreground">
                  {evidence.title}
                </p>
                {evidence.description && (
                  <p className="text-caption text-muted-foreground mt-1">
                    {evidence.description}
                  </p>
                )}
              </div>
            </div>
            {checks.length > 0 && (
              <div className="space-y-2 mt-4">
                {checks.map((check, i) => (
                    <div
                      key={i}
                      className={cn(
                        "flex items-center gap-2 rounded-lg px-3 py-2 text-caption",
                        check.passed
                          ? "bg-emerald-500/5 text-emerald-700"
                          : "bg-destructive/5 text-destructive"
                      )}
                    >
                      <MaterialIcon
                        name={check.passed ? "check" : "close"}
                        size={14}
                      />
                      <span>{check.message || check.type}</span>
                    </div>
                  )
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="w-full rounded-xl border border-border bg-card p-6 text-center">
            <MaterialIcon name="description" size={48} className="mx-auto mb-3 text-muted-foreground/40" />
            <p className="text-body-sm text-muted-foreground">
              This evidence type cannot be previewed here.
            </p>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center gap-4 mt-3 text-caption text-muted-foreground/80">
          <span className="capitalize">{evidence.type.toLowerCase()}</span>
          <span>{new Date(evidence.createdAt).toLocaleTimeString()}</span>
        </div>
      </div>
    </div>
  );
}
