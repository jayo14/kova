"use client";

import { useEffect, useState } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  createCheckout,
  createPortal,
  getInvoices,
  getSubscription,
  type Invoice,
  type Subscription,
} from "@/lib/api/billing";
import { getUsage, type UsageSummary } from "@/lib/api/usage";

interface BillingContentProps {
  user: {
    id: string;
    email?: string;
  };
  organizationName?: string;
}

export function BillingContent({ user, organizationName }: BillingContentProps) {
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      setLoading(true);
      setError(null);
      try {
        const [sub, usg, invs] = await Promise.all([
          getSubscription().catch(() => null),
          getUsage().catch(() => null),
          getInvoices().catch(() => []),
        ]);
        if (sub) setSubscription(sub);
        if (usg) setUsage(usg);
        if (invs) setInvoices(invs);
      } catch (err: any) {
        setError(err.message || "Failed to load billing details");
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  const handleUpgrade = async (plan: "pro" | "enterprise") => {
    setActionLoading(plan);
    try {
      const res = await createCheckout(plan);
      if (res?.checkout_url) {
        window.location.href = res.checkout_url;
      }
    } catch (err: any) {
      alert(err.message || "Failed to initiate checkout");
      setActionLoading(null);
    }
  };

  const handlePortal = async () => {
    setActionLoading("portal");
    try {
      const res = await createPortal();
      if (res?.portal_url) {
        window.location.href = res.portal_url;
      }
    } catch (err: any) {
      alert(err.message || "Failed to open billing portal");
      setActionLoading(null);
    }
  };

  const currentPlan = subscription?.plan || usage?.plan || "free";
  const currentStatus = subscription?.status || "active";

  const execUsagePct = usage
    ? Math.min(100, Math.round((usage.executions_this_month / Math.max(1, usage.executions_limit)) * 100))
    : 0;
  const storageUsagePct = usage
    ? Math.min(100, Math.round((usage.evidence_storage_mb / Math.max(1, usage.evidence_storage_limit_mb)) * 100))
    : 0;

  return (
    <div className="space-y-8 max-w-6xl mx-auto py-4">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border/60 pb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Billing & Plans</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage your subscription, plan limits, usage metering, and payment methods for {organizationName || "your workspace"}.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            onClick={handlePortal}
            disabled={actionLoading === "portal"}
            className="flex items-center gap-2"
          >
            <MaterialIcon name="credit_card" size={16} />
            {actionLoading === "portal" ? "Opening..." : "Manage Billing & Cards"}
          </Button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm flex items-center gap-2">
          <MaterialIcon name="error" size={18} />
          <span>{error}</span>
        </div>
      )}

      {/* Usage Overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="p-5 rounded-2xl border border-border/70 bg-card/60 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Current Plan</span>
            <Badge variant={currentPlan === "free" ? "secondary" : "default"} className="uppercase font-mono text-xs">
              {currentPlan}
            </Badge>
          </div>
          <div className="text-2xl font-bold capitalize">{currentPlan} Tier</div>
          <div className="text-xs text-muted-foreground flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${currentStatus === "active" ? "bg-emerald-500" : "bg-amber-500"}`} />
            Status: <span className="capitalize font-medium text-foreground">{currentStatus}</span>
          </div>
        </div>

        <div className="p-5 rounded-2xl border border-border/70 bg-card/60 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Monthly Executions</span>
            <span className="text-xs font-mono text-muted-foreground">{execUsagePct}%</span>
          </div>
          <div className="text-2xl font-bold">
            {usage ? usage.executions_this_month : 0} <span className="text-sm font-normal text-muted-foreground">/ {usage ? usage.executions_limit : 50}</span>
          </div>
          <div className="w-full bg-secondary/80 h-2 rounded-full overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ${execUsagePct > 90 ? "bg-destructive" : "bg-primary"}`}
              style={{ width: `${execUsagePct}%` }}
            />
          </div>
          <div className="text-xs text-muted-foreground">
            {usage ? usage.executions_remaining : 50} runs remaining in cycle
          </div>
        </div>

        <div className="p-5 rounded-2xl border border-border/70 bg-card/60 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Evidence Storage</span>
            <span className="text-xs font-mono text-muted-foreground">{storageUsagePct}%</span>
          </div>
          <div className="text-2xl font-bold">
            {usage ? usage.evidence_storage_mb : 0} <span className="text-sm font-normal text-muted-foreground">/ {usage ? usage.evidence_storage_limit_mb : 100} MB</span>
          </div>
          <div className="w-full bg-secondary/80 h-2 rounded-full overflow-hidden">
            <div
              className="h-full bg-primary transition-all duration-500"
              style={{ width: `${storageUsagePct}%` }}
            />
          </div>
          <div className="text-xs text-muted-foreground">
            Screenshots, video traces, and DOM snapshot storage
          </div>
        </div>
      </div>

      {/* Plan Tiers */}
      <div>
        <h2 className="text-lg font-semibold tracking-tight mb-4">Available Subscription Plans</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Free Tier */}
          <div className={`p-6 rounded-2xl border ${currentPlan === "free" ? "border-primary/60 bg-primary/5" : "border-border/70 bg-card/40"} flex flex-col justify-between space-y-6 shadow-sm`}>
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-bold text-lg">Free</h3>
                {currentPlan === "free" && <Badge variant="secondary">Current</Badge>}
              </div>
              <div className="text-3xl font-extrabold mb-4">$0 <span className="text-sm font-normal text-muted-foreground">/ month</span></div>
              <ul className="space-y-2.5 text-sm text-muted-foreground">
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span>50 flow executions / mo</span>
                </li>
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span>1 project</span>
                </li>
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span>1 CI integration (GitHub)</span>
                </li>
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span>100 MB evidence storage</span>
                </li>
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span>Community support</span>
                </li>
              </ul>
            </div>
            <Button variant="outline" disabled={currentPlan === "free"} className="w-full">
              {currentPlan === "free" ? "Active Plan" : "Downgrade to Free"}
            </Button>
          </div>

          {/* Pro Tier */}
          <div className={`p-6 rounded-2xl border ${currentPlan === "pro" ? "border-primary ring-2 ring-primary/20 bg-primary/5" : "border-primary/40 bg-card/70"} flex flex-col justify-between space-y-6 shadow-md relative`}>
            {currentPlan !== "pro" && (
              <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-primary text-primary-foreground text-xs font-semibold px-3 py-0.5 rounded-full uppercase tracking-wider">
                Most Popular
              </div>
            )}
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-bold text-lg text-primary">Pro</h3>
                {currentPlan === "pro" && <Badge>Current</Badge>}
              </div>
              <div className="text-3xl font-extrabold mb-4">$49 <span className="text-sm font-normal text-muted-foreground">/ month</span></div>
              <ul className="space-y-2.5 text-sm text-foreground/90">
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span className="font-medium">500 flow executions / mo</span>
                </li>
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span>Up to 5 projects</span>
                </li>
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span>3 integrations (GitHub, GitLab, Slack)</span>
                </li>
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span>5 GB evidence storage</span>
                </li>
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span>Autonomous self-healing flows</span>
                </li>
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span>Priority email support</span>
                </li>
              </ul>
            </div>
            <Button
              onClick={() => handleUpgrade("pro")}
              disabled={currentPlan === "pro" || actionLoading === "pro"}
              className="w-full"
            >
              {currentPlan === "pro" ? "Active Plan" : actionLoading === "pro" ? "Redirecting..." : "Upgrade to Pro"}
            </Button>
          </div>

          {/* Enterprise Tier */}
          <div className={`p-6 rounded-2xl border ${currentPlan === "enterprise" ? "border-primary/80 bg-primary/5" : "border-border/70 bg-card/40"} flex flex-col justify-between space-y-6 shadow-sm`}>
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-bold text-lg">Enterprise</h3>
                {currentPlan === "enterprise" && <Badge>Current</Badge>}
              </div>
              <div className="text-3xl font-extrabold mb-4">$299 <span className="text-sm font-normal text-muted-foreground">/ month</span></div>
              <ul className="space-y-2.5 text-sm text-muted-foreground">
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span className="font-medium">5,000 flow executions / mo</span>
                </li>
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span>Unlimited projects</span>
                </li>
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span>Unlimited integrations & Jira sync</span>
                </li>
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span>50 GB evidence storage</span>
                </li>
                <li className="flex items-center gap-2">
                  <MaterialIcon name="check" size={16} className="text-primary" />
                  <span>Dedicated Slack channel & SLA</span>
                </li>
              </ul>
            </div>
            <Button
              variant={currentPlan === "enterprise" ? "outline" : "default"}
              onClick={() => handleUpgrade("enterprise")}
              disabled={currentPlan === "enterprise" || actionLoading === "enterprise"}
              className="w-full"
            >
              {currentPlan === "enterprise" ? "Active Plan" : actionLoading === "enterprise" ? "Redirecting..." : "Upgrade to Enterprise"}
            </Button>
          </div>
        </div>
      </div>

      {/* Invoice History */}
      <div className="border border-border/70 rounded-2xl bg-card/40 p-6 space-y-4">
        <h2 className="text-lg font-semibold tracking-tight">Invoice History</h2>
        {invoices.length === 0 ? (
          <div className="text-sm text-muted-foreground py-6 text-center">
            No invoices generated yet for this workspace.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="text-xs uppercase text-muted-foreground border-b border-border/60">
                <tr>
                  <th className="py-2.5 px-3">Date</th>
                  <th className="py-2.5 px-3">Invoice ID</th>
                  <th className="py-2.5 px-3">Amount</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3 text-right">Receipt</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {invoices.map((inv) => (
                  <tr key={inv.id} className="hover:bg-muted/30 transition-colors">
                    <td className="py-3 px-3 text-muted-foreground font-mono text-xs">
                      {new Date(inv.created_at).toLocaleDateString()}
                    </td>
                    <td className="py-3 px-3 font-mono text-xs">{inv.stripe_invoice_id}</td>
                    <td className="py-3 px-3 font-medium">
                      {(inv.amount_paid / 100).toLocaleString("en-US", {
                        style: "currency",
                        currency: inv.currency.toUpperCase(),
                      })}
                    </td>
                    <td className="py-3 px-3">
                      <Badge variant={inv.status === "paid" ? "outline" : "destructive"} className="text-xs capitalize">
                        {inv.status}
                      </Badge>
                    </td>
                    <td className="py-3 px-3 text-right">
                      {inv.hosted_invoice_url ? (
                        <a
                          href={inv.hosted_invoice_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-primary text-xs hover:underline inline-flex items-center gap-1"
                        >
                          View PDF
                          <MaterialIcon name="open_in_new" size={14} />
                        </a>
                      ) : (
                        <span className="text-muted-foreground text-xs">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
