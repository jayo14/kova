import { Skeleton } from "@/components/ui/skeleton";

export function MissionRowSkeleton() {
  return (
    <div className="flex items-center justify-between gap-4 rounded-xl border border-border/80 bg-card p-4 shadow-xs">
      <div className="space-y-2 flex-1">
        <Skeleton className="h-5 w-48 rounded-md" />
        <Skeleton className="h-4 w-32 rounded-md opacity-60" />
      </div>
      <div className="flex items-center gap-3">
        <Skeleton className="h-4 w-24 rounded-md hidden sm:block opacity-50" />
        <Skeleton className="h-4 w-4 rounded-full" />
      </div>
    </div>
  );
}

export function MissionListSkeleton() {
  return (
    <div className="space-y-4 animate-in fade-in duration-300">
      <div className="flex flex-col sm:flex-row gap-3">
        <Skeleton className="h-10 flex-1 rounded-xl" />
        <Skeleton className="h-10 w-32 rounded-xl hidden sm:block" />
      </div>

      <div className="space-y-2">
        <MissionRowSkeleton />
        <MissionRowSkeleton />
        <MissionRowSkeleton />
        <MissionRowSkeleton />
        <MissionRowSkeleton />
      </div>
    </div>
  );
}

export function MissionDetailSkeleton() {
  return (
    <div className="w-full max-w-4xl mx-auto space-y-8 animate-in fade-in duration-300">
      {/* Breadcrumb & Header */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Skeleton className="h-4 w-16 rounded-md" />
          <span className="text-border">/</span>
          <Skeleton className="h-4 w-36 rounded-md" />
        </div>

        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-2">
            <Skeleton className="h-9 w-64 rounded-lg" />
            <Skeleton className="h-4 w-40 rounded-md opacity-60" />
          </div>

          <div className="flex items-center gap-2">
            <Skeleton className="h-9 w-20 rounded-xl" />
            <Skeleton className="h-9 w-28 rounded-xl" />
          </div>
        </div>
      </div>

      {/* Command Surface */}
      <div className="rounded-2xl border border-border/80 bg-card/60 p-5 space-y-3">
        <Skeleton className="h-4 w-44 rounded-md" />
        <Skeleton className="h-10 w-full rounded-xl" />
        <div className="flex gap-2">
          <Skeleton className="h-5 w-28 rounded-md" />
          <Skeleton className="h-5 w-36 rounded-md" />
        </div>
      </div>

      {/* 2-Column Content */}
      <div className="grid gap-8 lg:grid-cols-3">
        <div className="space-y-8 lg:col-span-2">
          {/* Objective */}
          <div className="space-y-2">
            <Skeleton className="h-4 w-24 rounded-md" />
            <Skeleton className="h-5 w-full rounded-md opacity-70" />
            <Skeleton className="h-5 w-3/4 rounded-md opacity-70" />
          </div>

          {/* Persona */}
          <div className="space-y-2">
            <Skeleton className="h-4 w-20 rounded-md" />
            <Skeleton className="h-8 w-28 rounded-lg" />
          </div>

          {/* Success Condition */}
          <div className="space-y-2">
            <Skeleton className="h-4 w-32 rounded-md" />
            <Skeleton className="h-14 w-full rounded-xl opacity-80" />
          </div>

          {/* Journey */}
          <div className="space-y-3 border-t border-border/60 pt-6">
            <Skeleton className="h-4 w-28 rounded-md" />
            <Skeleton className="h-6 w-full rounded-md opacity-60" />
            <Skeleton className="h-6 w-full rounded-md opacity-60" />
            <Skeleton className="h-6 w-full rounded-md opacity-60" />
          </div>
        </div>

        {/* Executions */}
        <div className="border-t border-border/60 pt-6 lg:border-t-0 lg:border-l lg:border-border/60 lg:pl-8 lg:pt-0 space-y-4">
          <Skeleton className="h-4 w-28 rounded-md" />
          <Skeleton className="h-20 w-full rounded-2xl" />
          <div className="space-y-2 pt-2">
            <Skeleton className="h-5 w-full rounded-md opacity-60" />
            <Skeleton className="h-5 w-full rounded-md opacity-60" />
          </div>
        </div>
      </div>
    </div>
  );
}
