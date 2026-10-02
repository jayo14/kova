import { Skeleton } from "@/components/ui/skeleton";

export function CredentialRowSkeleton() {
  return (
    <div className="rounded-xl border border-border/60 bg-card/40 p-3.5 sm:px-4">
      {/* Desktop */}
      <div className="hidden md:grid md:grid-cols-12 md:items-center md:gap-4">
        <div className="col-span-3 flex items-center gap-2">
          <Skeleton className="h-7 w-7 rounded-lg shrink-0" />
          <Skeleton className="h-4 w-28 rounded-md" />
        </div>
        <div className="col-span-3">
          <Skeleton className="h-4 w-36 rounded-md opacity-70" />
        </div>
        <div className="col-span-2">
          <Skeleton className="h-5 w-16 rounded-full opacity-60" />
        </div>
        <div className="col-span-2">
          <Skeleton className="h-4 w-24 rounded-md opacity-60" />
        </div>
        <div className="col-span-1 flex justify-end">
          <Skeleton className="h-3 w-12 rounded-md opacity-50" />
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
            <Skeleton className="h-4 w-28 rounded-md" />
          </div>
          <Skeleton className="h-6 w-6 rounded-md opacity-40" />
        </div>
        <Skeleton className="h-3 w-36 rounded-md opacity-60" />
        <div className="flex items-center gap-2 pt-1">
          <Skeleton className="h-4 w-14 rounded-full opacity-50" />
          <Skeleton className="h-3 w-20 rounded-md opacity-50" />
          <Skeleton className="ml-auto h-3 w-12 rounded-md opacity-40" />
        </div>
      </div>
    </div>
  );
}

export function CredentialListSkeleton() {
  return (
    <div className="space-y-4 animate-in fade-in duration-300">
      <div className="flex items-center gap-3">
        <Skeleton className="h-10 flex-1 rounded-xl" />
      </div>

      <div className="space-y-2">
        <CredentialRowSkeleton />
        <CredentialRowSkeleton />
        <CredentialRowSkeleton />
        <CredentialRowSkeleton />
      </div>
    </div>
  );
}
