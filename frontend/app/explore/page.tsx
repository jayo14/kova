"use client";

import { Suspense } from "react";
import ExplorePageContent from "./explore-content";

export default function ExplorePage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-background">
          <p className="text-body-sm text-muted-foreground">Loading...</p>
        </div>
      }
    >
      <ExplorePageContent />
    </Suspense>
  );
}
