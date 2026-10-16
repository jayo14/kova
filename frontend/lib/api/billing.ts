import { request } from "./client";

export interface Subscription {
  id: string;
  org_id: string;
  plan: "free" | "pro" | "enterprise";
  status: "active" | "trialing" | "past_due" | "canceled";
  stripe_customer_id?: string | null;
  stripe_subscription_id?: string | null;
  current_period_start?: string | null;
  current_period_end?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CheckoutSessionRequest {
  plan: "free" | "pro" | "enterprise";
  success_url?: string;
  cancel_url?: string;
}

export interface CheckoutSessionResponse {
  checkout_url: string;
  session_id: string;
}

export interface PortalSessionRequest {
  return_url?: string;
}

export interface PortalSessionResponse {
  portal_url: string;
}

export interface Invoice {
  id: string;
  org_id: string;
  stripe_invoice_id: string;
  amount_due: number;
  amount_paid: number;
  currency: string;
  status: string;
  hosted_invoice_url?: string | null;
  created_at: string;
}

export async function getSubscription(orgId?: string): Promise<Subscription> {
  const query = orgId ? `?org_id=${encodeURIComponent(orgId)}` : "";
  return request<Subscription>("GET", `/api/v1/billing/subscription${query}`);
}

export async function createCheckout(
  plan: "free" | "pro" | "enterprise",
  successUrl?: string,
  cancelUrl?: string,
  orgId?: string
): Promise<CheckoutSessionResponse> {
  const query = orgId ? `?org_id=${encodeURIComponent(orgId)}` : "";
  return request<CheckoutSessionResponse>(
    "POST",
    `/api/v1/billing/checkout${query}`,
    {
      plan,
      success_url: successUrl,
      cancel_url: cancelUrl,
    }
  );
}

export async function createPortal(
  returnUrl?: string,
  orgId?: string
): Promise<PortalSessionResponse> {
  const query = orgId ? `?org_id=${encodeURIComponent(orgId)}` : "";
  return request<PortalSessionResponse>(
    "POST",
    `/api/v1/billing/portal${query}`,
    {
      return_url: returnUrl,
    }
  );
}

export async function getInvoices(orgId?: string): Promise<Invoice[]> {
  const query = orgId ? `?org_id=${encodeURIComponent(orgId)}` : "";
  return request<Invoice[]>("GET", `/api/v1/billing/invoices${query}`);
}
