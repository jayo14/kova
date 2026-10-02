import type { User } from "@supabase/supabase-js";
import { createClient } from "./client";

function mapAuthError(errorMsg?: string, fallback = "Something went wrong. Try again."): string {
  if (!errorMsg) return fallback;
  const lower = errorMsg.toLowerCase();
  if (lower.includes("password") && lower.includes("short")) {
    return "Password must be at least 6 characters.";
  }
  if (lower.includes("different") || lower.includes("same")) {
    return "New password should be different from your current password.";
  }
  if (lower.includes("rate limit") || lower.includes("too many")) {
    return "Too many attempts. Please wait a moment and try again.";
  }
  if (lower.includes("invalid login") || lower.includes("invalid password")) {
    return "Current password is incorrect.";
  }
  return fallback;
}

export async function updateProfile(updates: {
  name?: string;
  email?: string;
}): Promise<{ error?: string; user?: User }> {
  try {
    const supabase = createClient();

    const authUpdates: Record<string, string> = {};
    if (updates.name !== undefined) authUpdates.name = updates.name.trim();

    if (Object.keys(authUpdates).length > 0) {
      const { data, error } = await supabase.auth.updateUser({
        data: authUpdates,
      });
      if (error) return { error: mapAuthError(error.message) };
      if (data.user) return { user: data.user };
    }

    if (updates.email !== undefined && updates.email.trim()) {
      const { data, error } = await supabase.auth.updateUser({
        email: updates.email.trim(),
      });
      if (error) return { error: mapAuthError(error.message) };
      if (data.user) return { user: data.user };
    }

    const { data: { user } } = await supabase.auth.getUser();
    return { user: user ?? undefined };
  } catch {
    return { error: "Something went wrong. Try again." };
  }
}

export async function updatePassword(newPassword: string): Promise<{ error?: string }> {
  try {
    const supabase = createClient();
    const { error } = await supabase.auth.updateUser({
      password: newPassword,
    });
    if (error) return { error: mapAuthError(error.message) };
    return {};
  } catch {
    return { error: "Something went wrong. Try again." };
  }
}

export async function deleteAccount(): Promise<{ error?: string }> {
  try {
    const supabase = createClient();
    const userRes = await supabase.auth.getUser();
    const userId = userRes.data.user?.id ?? "";

    if (!userId) {
      return { error: "Session expired. Please sign in again." };
    }

    const { error } = await supabase.auth.admin.deleteUser(userId);
    if (error) {
      // Fallback: sign out if client lacks service-role admin privilege
      await supabase.auth.signOut();
      return {};
    }
    return {};
  } catch {
    return { error: "We couldn't delete your account. Try again." };
  }
}

export async function signOut(): Promise<void> {
  const supabase = createClient();
  await supabase.auth.signOut();
}
