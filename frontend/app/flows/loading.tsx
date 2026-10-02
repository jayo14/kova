import { MissionListSkeleton } from "@/components/flows/mission-skeleton";
import { Skeleton } from "@/components/ui/skeleton";

export default function FlowsLoading() {
  return (
    <div className="w-full max-w-4xl mx-auto px-6 py-10 md:py-14 space-y-8 animate-in fade-in duration-300">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <Skeleton className="h-9 w-40 rounded-lg" />
          <Skeleton className="h-4 w-64 rounded-md opacity-60" />
        </div>
        <Skeleton className="h-10 w-36 rounded-xl" />
      </div>

      <MissionListSkeleton />
    </div>
  );
}
