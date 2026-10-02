import { Skeleton } from "@/components/ui/skeleton";

export function AccountSkeleton() {
  return (
    <div className="rounded-2xl border border-border/70 bg-card/50 p-6 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1.5">
          <Skeleton className="h-5 w-24 rounded-md" />
          <Skeleton className="h-4 w-60 rounded-md opacity-60" />
        </div>
        <Skeleton className="h-8 w-24 rounded-xl shrink-0" />
      </div>
      <div className="space-y-3 pt-2 border-t border-border/50">
        <div className="space-y-1">
          <Skeleton className="h-3 w-16 rounded-md opacity-60" />
          <Skeleton className="h-4 w-36 rounded-md" />
        </div>
        <div className="space-y-1">
          <Skeleton className="h-3 w-16 rounded-md opacity-60" />
          <Skeleton className="h-4 w-48 rounded-md" />
        </div>
      </div>
    </div>
  );
}

export function PasswordSkeleton() {
  return (
    <div className="rounded-2xl border border-border/70 bg-card/50 p-6 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1.5">
          <Skeleton className="h-5 w-24 rounded-md" />
          <Skeleton className="h-4 w-64 rounded-md opacity-60" />
        </div>
        <Skeleton className="h-8 w-32 rounded-xl shrink-0" />
      </div>
      <div className="space-y-1 pt-2 border-t border-border/50">
        <Skeleton className="h-3 w-28 rounded-md opacity-60" />
        <Skeleton className="h-4 w-36 rounded-md" />
      </div>
    </div>
  );
}

export function SessionSkeleton() {
  return (
    <div className="rounded-2xl border border-border/70 bg-card/50 p-6 space-y-4">
      <div className="space-y-1.5">
        <Skeleton className="h-5 w-20 rounded-md" />
        <Skeleton className="h-4 w-52 rounded-md opacity-60" />
      </div>
      <div className="pt-2 border-t border-border/50">
        <Skeleton className="h-8 w-24 rounded-xl" />
      </div>
    </div>
  );
}

export function AppearanceSkeleton() {
  return (
    <div className="rounded-2xl border border-border/70 bg-card/50 p-6 space-y-4">
      <div className="space-y-1.5">
        <Skeleton className="h-5 w-28 rounded-md" />
        <Skeleton className="h-4 w-64 rounded-md opacity-60" />
      </div>
      <div className="flex gap-3 pt-2 border-t border-border/50">
        <Skeleton className="h-9 w-24 rounded-xl" />
        <Skeleton className="h-9 w-24 rounded-xl" />
        <Skeleton className="h-9 w-24 rounded-xl" />
      </div>
    </div>
  );
}

export function DangerZoneSkeleton() {
  return (
    <div className="rounded-2xl border border-destructive/20 bg-destructive/5 p-6 space-y-4">
      <div className="space-y-1.5">
        <Skeleton className="h-5 w-28 rounded-md" />
        <Skeleton className="h-4 w-72 rounded-md opacity-60" />
      </div>
      <div className="flex items-center justify-between gap-4 rounded-xl border border-destructive/20 bg-card p-4">
        <div className="space-y-1">
          <Skeleton className="h-4 w-28 rounded-md" />
          <Skeleton className="h-3 w-56 rounded-md opacity-60" />
        </div>
        <Skeleton className="h-8 w-28 rounded-xl shrink-0" />
      </div>
    </div>
  );
}

export function SettingsSkeleton() {
  return (
    <div className="w-full max-w-5xl mx-auto px-6 py-10 md:py-14 space-y-8 animate-in fade-in duration-300">
      <div className="space-y-2">
        <Skeleton className="h-9 w-40 rounded-lg" />
        <Skeleton className="h-4 w-72 rounded-md opacity-60" />
      </div>

      <div className="space-y-8 max-w-3xl">
        <AccountSkeleton />
        <PasswordSkeleton />
        <SessionSkeleton />
        <AppearanceSkeleton />
        <DangerZoneSkeleton />
      </div>
    </div>
  );
}
