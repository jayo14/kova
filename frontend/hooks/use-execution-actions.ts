"use client";

import { useCallback, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { ExecutionDetail } from "@/lib/types";
import {
  createExecution,
  getExecutionReport,
  mintShareableUrl,
  type ExecutionReport,
} from "@/lib/api/executions";
import { getApiBaseUrl } from "@/lib/api/client";

interface UseExecutionActionsOptions {
  execution: ExecutionDetail;
  report?: ExecutionReport | null;
}

export function useExecutionActions({
  execution,
  report,
}: UseExecutionActionsOptions) {
  const router = useRouter();
  const [actionError, setActionError] = useState<string | null>(null);
  const [isRetrying, startRetryTransition] = useTransition();
  const [shareLoading, setShareLoading] = useState(false);
  const [shareSuccess, setShareSuccess] = useState<string | null>(null);

  // Run again / Retry -> creates a NEW immutable execution
  const handleRetry = useCallback(() => {
    setActionError(null);
    startRetryTransition(async () => {
      try {
        const newExecution = await createExecution(execution.missionId);
        if (newExecution) {
          router.push(`/executions/${newExecution.id}`);
        } else {
          setActionError("Failed to start new execution.");
        }
      } catch {
        setActionError("Failed to start new execution.");
      }
    });
  }, [execution.missionId, router]);

  const handleShare = useCallback(async () => {
    setShareLoading(true);
    setShareSuccess(null);
    setActionError(null);
    try {
      const res = await mintShareableUrl(execution.id);
      if (res?.url) {
        if (typeof navigator !== "undefined" && navigator.clipboard) {
          await navigator.clipboard.writeText(res.url);
        }
        setShareSuccess("Link copied to clipboard!");
        setTimeout(() => setShareSuccess(null), 3500);
      } else {
        setActionError("Could not generate shareable link.");
      }
    } catch {
      setActionError("Failed to generate shareable link.");
    } finally {
      setShareLoading(false);
    }
  }, [execution.id]);

  const handleExportPdf = useCallback(async () => {
    setActionError(null);
    const base = getApiBaseUrl();
    const reportPath = `${base}/api/v1/executions/${encodeURIComponent(execution.id)}/report`;

    let signature = report?.signature ?? null;
    if (!signature) {
      try {
        signature = (await getExecutionReport(execution.id))?.signature ?? null;
      } catch {
        signature = null;
      }
    }

    if (!signature) {
      setActionError("Report is not ready yet. Reload the page and try again.");
      return;
    }

    window.open(
      `${reportPath}?signature=${encodeURIComponent(signature)}&format=html`,
      "_blank",
      "noopener,noreferrer"
    );
  }, [execution.id, report?.signature]);

  return {
    actionError,
    setActionError,
    isRetrying,
    shareLoading,
    shareSuccess,
    handleRetry,
    handleShare,
    handleExportPdf,
  };
}
