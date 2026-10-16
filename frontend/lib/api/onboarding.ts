import { request } from "./client";

export interface UserMe {
  id: string;
  email: string;
  name: string | null;
  onboarding_step: number;
}

export async function getMe(): Promise<UserMe> {
  return request<UserMe>("GET", "/api/v1/auth/me");
}

export async function updateOnboardingStep(step: number): Promise<{ onboarding_step: number }> {
  return request<{ onboarding_step: number }>("PATCH", "/api/v1/auth/me/onboarding", { step });
}
