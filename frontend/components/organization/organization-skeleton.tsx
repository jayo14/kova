import { Skeleton } from "@/components/ui/skeleton";

export function WorkspaceSkeleton() {
  return (
    <div className="rounded-2xl border border-border/70 bg-card/50 p-6 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1.5">
          <Skeleton className="h-5 w-28 rounded-md" />
          <Skeleton className="h-4 w-72 rounded-md opacity-60" />
        </div>
        <Skeleton className="h-8 w-16 rounded-xl shrink-0" />
      </div>

      <div className="space-y-1.5 pt-3 border-t border-border/50">
        <Skeleton className="h-3 w-24 rounded-md opacity-60" />
        <Skeleton className="h-5 w-40 rounded-md" />
      </div>
    </div>
  );
}

export function MemberRowSkeleton() {
  return (
    <div className="rounded-xl border border-border/60 bg-card/40 p-3.5 sm:px-4">
      {/* Desktop */}
      <div className="hidden md:grid md:grid-cols-12 md:items-center md:gap-4">
        <div className="col-span-4 flex items-center gap-2.5">
          <Skeleton className="h-7 w-7 rounded-lg shrink-0" />
          <Skeleton className="h-4 w-32 rounded-md" />
        </div>
        <div className="col-span-4">
          <Skeleton className="h-4 w-44 rounded-md opacity-70" />
        </div>
        <div className="col-span-3">
          <Skeleton className="h-5 w-16 rounded-full opacity-60" />
        </div>
        <div className="col-span-1 flex justify-end">
          <Skeleton className="h-7 w-7 rounded-lg opacity-40" />
        </div>
      </div>

      {/* Mobile */}
      <div className="flex flex-col gap-2 md:hidden">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Skeleton className="h-6 w-6 rounded-lg shrink-0" />
            <Skeleton className="h-4 w-32 rounded-md" />
          </div>
          <Skeleton className="h-6 w-6 rounded-md opacity-40" />
        </div>
        <Skeleton className="h-3 w-40 rounded-md opacity-60" />
        <div className="pt-1">
          <Skeleton className="h-4 w-14 rounded-full opacity-50" />
        </div>
      </div>
    </div>
  );
}

export function MemberListSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div className="space-y-1.5">
          <Skeleton className="h-5 w-24 rounded-md" />
          <Skeleton className="h-4 w-52 rounded-md opacity-60" />
        </div>
        <Skeleton className="h-8 w-28 rounded-xl shrink-0" />
      </div>

      <div className="space-y-2">
        <MemberRowSkeleton />
        <MemberRowSkeleton />
        <MemberRowSkeleton />
      </div>
    </div>
  );
}

export function OrganizationSkeleton() {
  return (
    <div className="w-full max-w-5xl mx-auto px-6 py-10 md:py-14 space-y-8 animate-in fade-in duration-300">
      <div className="space-y-2">
        <Skeleton className="h-9 w-48 rounded-lg" />
        <Skeleton className="h-4 w-80 rounded-md opacity-60" />
      </div>

      <WorkspaceSkeleton />
      <MemberListSkeleton />
    </div>
  );
}
