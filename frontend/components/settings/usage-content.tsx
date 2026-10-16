"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getUsage, type UsageSummary } from "@/lib/api/usage";

export function UsageContent() {
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchUsage() {
      setLoading(true);
      try {
        const data = await getUsage();
        setUsage(data);
      } catch (err) {
        console.error("Failed to load usage summary", err);
      } finally {
        setLoading(false);
      }
    }
    fetchUsage();
  }, []);

  const execPct = usage
    ? Math.min(100, Math.round((usage.executions_this_month / Math.max(1, usage.executions_limit)) * 100))
    : 0;
  const storagePct = usage
    ? Math.min(100, Math.round((usage.evidence_storage_mb / Math.max(1, usage.evidence_storage_limit_mb)) * 100))
    : 0;

  return (
    <div className="space-y-8 max-w-5xl mx-auto py-4">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border/60 pb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Usage & Quotas</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Monitor flow execution limits, evidence storage consumption, and plan limits.
          </p>
        </div>
        <div>
          <Link href="/billing">
            <Button className="flex items-center gap-2">
              <MaterialIcon name="upgrade" size={16} />
              Upgrade Plan
            </Button>
          </Link>
        </div>
      </div>

      {loading ? (
        <div className="py-12 text-center text-sm text-muted-foreground">Loading usage data...</div>
      ) : (
        <div className="space-y-6">
          {/* Billing Cycle Info */}
          <div className="p-4 rounded-xl border border-border/70 bg-card/40 flex items-center justify-between text-sm">
            <div className="flex items-center gap-2 text-muted-foreground">
              <MaterialIcon name="date_range" size={18} />
              <span>Current Billing Cycle:</span>
              <span className="font-mono text-foreground font-medium">
                {usage?.period_start ? new Date(usage.period_start).toLocaleDateString() : "First of month"}
                {" — "}
                {usage?.period_end ? new Date(usage.period_end).toLocaleDateString() : "End of month"}
              </span>
            </div>
            <Badge variant="outline" className="uppercase font-mono text-xs">
              {usage?.plan || "free"} Plan
            </Badge>
          </div>

          {/* Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="p-6 rounded-2xl border border-border/70 bg-card/60 space-y-4 shadow-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="p-2 rounded-lg bg-primary/10 text-primary">
                    <MaterialIcon name="play_arrow" size={20} />
                  </div>
                  <div>
                    <h2 className="font-bold">Monthly Flow Executions</h2>
                    <p className="text-xs text-muted-foreground">CI validations and regression runs</p>
                  </div>
                </div>
                <span className="font-mono text-sm font-semibold">{execPct}%</span>
              </div>

              <div className="space-y-2">
                <div className="w-full bg-secondary/80 h-3 rounded-full overflow-hidden">
                  <div
                    className={`h-full transition-all duration-500 ${execPct > 85 ? "bg-destructive" : "bg-primary"}`}
                    style={{ width: `${execPct}%` }}
                  />
                </div>
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>Used: {usage?.executions_this_month ?? 0}</span>
                  <span>Limit: {usage?.executions_limit ?? 50} runs</span>
                </div>
              </div>

              <div className="pt-2 text-xs border-t border-border/40 text-muted-foreground flex items-center justify-between">
                <span>Remaining in period:</span>
                <span className="font-semibold text-foreground">{usage?.executions_remaining ?? 50}</span>
              </div>
            </div>

            <div className="p-6 rounded-2xl border border-border/70 bg-card/60 space-y-4 shadow-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="p-2 rounded-lg bg-primary/10 text-primary">
                    <MaterialIcon name="folder_zip" size={20} />
                  </div>
                  <div>
                    <h2 className="font-bold">Evidence Storage</h2>
                    <p className="text-xs text-muted-foreground">Trace artifacts, screenshots, and logs</p>
                  </div>
                </div>
                <span className="font-mono text-sm font-semibold">{storagePct}%</span>
              </div>

              <div className="space-y-2">
                <div className="w-full bg-secondary/80 h-3 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary transition-all duration-500"
                    style={{ width: `${storagePct}%` }}
                  />
                </div>
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>Used: {usage?.evidence_storage_mb ?? 0} MB</span>
                  <span>Limit: {usage?.evidence_storage_limit_mb ?? 100} MB</span>
                </div>
              </div>

              <div className="pt-2 text-xs border-t border-border/40 text-muted-foreground flex items-center justify-between">
                <span>Storage utilization:</span>
                <span className="font-semibold text-foreground">
                  {((usage?.evidence_storage_limit_mb ?? 100) - (usage?.evidence_storage_mb ?? 0)).toFixed(1)} MB available
                </span>
              </div>
            </div>
          </div>

          {/* Limit Notice */}
          {usage && usage.executions_this_month >= usage.executions_limit && (
            <div className="p-5 rounded-2xl bg-destructive/10 border border-destructive/30 text-destructive flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <MaterialIcon name="error" size={24} />
                <div>
                  <div className="font-bold text-sm">Execution limit reached for this billing period</div>
                  <div className="text-xs text-destructive/80 mt-0.5">
                    CI runs will return HTTP 402 Payment Required until you upgrade your subscription.
                  </div>
                </div>
              </div>
              <Link href="/billing">
                <Button size="sm" variant="destructive">
                  Upgrade Now
                </Button>
              </Link>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
