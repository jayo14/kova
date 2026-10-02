import { Skeleton } from "@/components/ui/skeleton";

export function ProjectSkeleton() {
  return (
    <div className="rounded-2xl border border-border/80 bg-card/60 p-5 shadow-xs">
      <div className="flex items-start justify-between gap-4 mb-3">
        <Skeleton className="h-5 w-40 rounded-md" />
        <Skeleton className="h-5 w-16 rounded-full" />
      </div>
      <Skeleton className="h-4 w-32 rounded-md mb-3 opacity-60" />
      <Skeleton className="h-4 w-full rounded-md opacity-40 mb-1" />
      <Skeleton className="h-4 w-2/3 rounded-md opacity-40" />
    </div>
  );
}

export function ProjectListSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <ProjectSkeleton />
      <ProjectSkeleton />
      <ProjectSkeleton />
      <ProjectSkeleton />
      <ProjectSkeleton />
      <ProjectSkeleton />
    </div>
  );
}

export function ProjectDetailSkeleton() {
  return (
    <div className="w-full max-w-5xl mx-auto space-y-8 animate-in fade-in duration-300">
      {/* Breadcrumb & Header */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Skeleton className="h-4 w-16 rounded-md" />
          <span className="text-border">/</span>
          <Skeleton className="h-4 w-28 rounded-md" />
        </div>

        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-2">
            <Skeleton className="h-8 w-60 rounded-lg" />
            <Skeleton className="h-4 w-44 rounded-md opacity-70" />
          </div>

          <div className="flex items-center gap-2">
            <Skeleton className="h-9 w-24 rounded-xl" />
            <Skeleton className="h-9 w-32 rounded-xl" />
          </div>
        </div>
      </div>

      {/* Command Input Box */}
      <div className="rounded-2xl border border-border/80 bg-card/60 p-6 space-y-3">
        <Skeleton className="h-4 w-52 rounded-md" />
        <Skeleton className="h-12 w-full rounded-xl" />
        <div className="flex gap-2">
          <Skeleton className="h-6 w-28 rounded-full" />
          <Skeleton className="h-6 w-36 rounded-full" />
        </div>
      </div>

      {/* 2-Column Grid */}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {/* About Product */}
          <div className="rounded-2xl border border-border/80 bg-card/60 p-6 space-y-4">
            <Skeleton className="h-5 w-36 rounded-md" />
            <Skeleton className="h-4 w-full rounded-md opacity-60" />
            <Skeleton className="h-4 w-3/4 rounded-md opacity-60" />
            <div className="border-t border-border/60 pt-4 space-y-2">
              <Skeleton className="h-4 w-48 rounded-md opacity-50" />
              <Skeleton className="h-4 w-56 rounded-md opacity-50" />
            </div>
          </div>

          {/* Missions */}
          <div className="rounded-2xl border border-border/80 bg-card/60 p-6 space-y-4">
            <div className="flex items-center justify-between">
              <Skeleton className="h-5 w-24 rounded-md" />
              <Skeleton className="h-5 w-8 rounded-full" />
            </div>
            <div className="space-y-3">
              <Skeleton className="h-14 w-full rounded-xl opacity-70" />
              <Skeleton className="h-14 w-full rounded-xl opacity-70" />
              <Skeleton className="h-14 w-full rounded-xl opacity-70" />
            </div>
          </div>
        </div>

        {/* Activity */}
        <div>
          <div className="rounded-2xl border border-border/80 bg-card/60 p-6 space-y-4">
            <div className="flex items-center justify-between">
              <Skeleton className="h-5 w-32 rounded-md" />
              <Skeleton className="h-5 w-8 rounded-full" />
            </div>
            <div className="space-y-4">
              <Skeleton className="h-10 w-full rounded-md opacity-70" />
              <Skeleton className="h-10 w-full rounded-md opacity-70" />
              <Skeleton className="h-10 w-full rounded-md opacity-70" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
