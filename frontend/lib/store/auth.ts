"use client";

import { create } from "zustand";
import { createClient } from "@/lib/auth/client";
import type { User, Session } from "@/lib/auth/custom";

interface AuthState {
  user: User | null;
  session: Session | null;
  loading: boolean;
  initialized: boolean;
  setUser: (user: User | null) => void;
  setSession: (session: Session | null) => void;
  initialize: () => Promise<void>;
  signOut: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  session: null,
  loading: true,
  initialized: false,

  setUser: (user) => set({ user }),
  setSession: (session) => set({ session }),

  initialize: async () => {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();

    set({
      session,
      user: session?.user ?? null,
      loading: false,
      initialized: true,
    });

    supabase.auth.onAuthStateChange((_event: any, session: any) => {
      set({
        session,
        user: session?.user ?? null,
      });
    });
  },

  signOut: async () => {
    const supabase = createClient();
    await supabase.auth.signOut();
    set({ user: null, session: null });
  },
}));
