import { ExecutionListSkeleton } from "@/components/executions/execution-skeleton";
import { Skeleton } from "@/components/ui/skeleton";

export default function ExecutionsLoading() {
  return (
    <div className="w-full max-w-5xl mx-auto px-6 py-10 md:py-14 space-y-8 animate-in fade-in duration-300">
      <div className="space-y-2">
        <Skeleton className="h-9 w-40 rounded-lg" />
        <Skeleton className="h-4 w-60 rounded-md opacity-60" />
      </div>

      <ExecutionListSkeleton />
    </div>
  );
}
