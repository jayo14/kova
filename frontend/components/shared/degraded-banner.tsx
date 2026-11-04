"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
import { checkBackendReadiness, type ReadyCheckResponse } from "@/lib/api/health";

export function DegradedBanner() {
  const [readyInfo, setReadyInfo] = useState<ReadyCheckResponse | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let active = true;

    async function pollReadiness() {
      const data = await checkBackendReadiness(4000);
      if (active) {
        setReadyInfo(data);
      }
    }

    pollReadiness();
    const interval = setInterval(pollReadiness, 20000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  if (dismissed || !readyInfo || readyInfo.status !== "degraded") {
    return null;
  }

  const workerMsg = readyInfo.worker?.message;

  return (
    <div
      role="status"
      className="bg-amber-500/15 border-b border-amber-500/30 text-amber-950 dark:text-amber-200 px-4 py-2 text-xs flex items-center justify-between transition-all duration-300"
    >
      <div className="flex items-center gap-2 max-w-4xl mx-auto flex-1">
        <MaterialIcon name="warning" size={16} className="text-amber-500 shrink-0" />
        <span className="font-semibold">Service degraded:</span>
        <span className="truncate">
          {workerMsg || "Worker or background services are temporarily experiencing delays."}
        </span>
        <Link href="/status" className="underline hover:text-foreground font-medium ml-1 shrink-0">
          View Status →
        </Link>
      </div>
      <button
        onClick={() => setDismissed(true)}
        aria-label="Dismiss banner"
        className="p-1 hover:bg-amber-500/20 rounded text-amber-700 dark:text-amber-300 ml-2 shrink-0"
      >
        <MaterialIcon name="close" size={14} />
      </button>
    </div>
  );
}
