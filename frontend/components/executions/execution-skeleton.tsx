import { Skeleton } from "@/components/ui/skeleton";

export function ExecutionRowSkeleton() {
  return (
    <div className="flex items-center justify-between gap-4 rounded-xl border border-border/80 bg-card p-4 shadow-xs">
      <div className="space-y-1.5 flex-1">
        <Skeleton className="h-5 w-52 rounded-md" />
        <Skeleton className="h-4 w-28 rounded-md opacity-60" />
      </div>
      <div className="flex items-center gap-3">
        <Skeleton className="h-6 w-24 rounded-md" />
        <Skeleton className="h-4 w-16 rounded-md hidden sm:block opacity-50" />
        <Skeleton className="h-4 w-4 rounded-full" />
      </div>
    </div>
  );
}

export function ExecutionListSkeleton() {
  return (
    <div className="space-y-4 animate-in fade-in duration-300">
      <div className="flex flex-col sm:flex-row gap-3">
        <Skeleton className="h-10 flex-1 rounded-xl" />
        <Skeleton className="h-10 w-48 rounded-xl hidden sm:block" />
      </div>

      <div className="space-y-2">
        <ExecutionRowSkeleton />
        <ExecutionRowSkeleton />
        <ExecutionRowSkeleton />
        <ExecutionRowSkeleton />
        <ExecutionRowSkeleton />
      </div>
    </div>
  );
}

export function ExecutionDetailSkeleton() {
  return (
    <div className="w-full max-w-5xl mx-auto space-y-6 animate-in fade-in duration-300">
      {/* Breadcrumb & Header */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Skeleton className="h-4 w-16 rounded-md" />
          <span className="text-border">/</span>
          <Skeleton className="h-4 w-24 rounded-md" />
        </div>

        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-2">
            <Skeleton className="h-9 w-64 rounded-lg" />
            <Skeleton className="h-4 w-48 rounded-md opacity-60" />
          </div>
          <Skeleton className="h-9 w-24 rounded-xl" />
        </div>
      </div>

      {/* Dominant Browser Viewport Skeleton */}
      <div className="rounded-2xl border border-border/80 bg-card overflow-hidden">
        <div className="flex items-center justify-between border-b border-border/70 bg-secondary/30 px-4 py-2.5">
          <div className="flex gap-1.5">
            <Skeleton className="h-2.5 w-2.5 rounded-full" />
            <Skeleton className="h-2.5 w-2.5 rounded-full" />
            <Skeleton className="h-2.5 w-2.5 rounded-full" />
          </div>
          <Skeleton className="h-6 w-48 rounded-lg" />
          <Skeleton className="h-4 w-4 rounded-full" />
        </div>
        <div className="h-[380px] flex flex-col items-center justify-center gap-3">
          <Skeleton className="h-14 w-14 rounded-2xl" />
          <Skeleton className="h-5 w-44 rounded-md" />
          <Skeleton className="h-4 w-60 rounded-md opacity-60" />
        </div>
      </div>

      {/* Lower Panels: Activity and Result */}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-3">
          <Skeleton className="h-5 w-32 rounded-md" />
          <div className="space-y-2">
            <Skeleton className="h-10 w-full rounded-xl" />
            <Skeleton className="h-10 w-full rounded-xl" />
            <Skeleton className="h-10 w-full rounded-xl" />
          </div>
        </div>
        <div className="space-y-3">
          <Skeleton className="h-5 w-24 rounded-md" />
          <Skeleton className="h-32 w-full rounded-2xl" />
        </div>
      </div>
    </div>
  );
}
