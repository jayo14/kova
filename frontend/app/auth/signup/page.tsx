"use client";

import { Suspense } from "react";
import { SignupContent } from "./signup-content";

export default function SignupPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-background">
          <div className="h-8 w-8 rounded-full border-2 border-primary/20 border-t-primary animate-spin" />
        </div>
      }
    >
      <SignupContent />
    </Suspense>
  );
}
