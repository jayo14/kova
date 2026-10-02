import { ProjectListSkeleton } from "@/components/projects/project-skeleton";
import { Skeleton } from "@/components/ui/skeleton";

export default function ProjectsLoading() {
  return (
    <div className="w-full max-w-5xl mx-auto space-y-8 animate-in fade-in duration-300">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-2">
          <Skeleton className="h-8 w-40 rounded-lg" />
          <Skeleton className="h-4 w-72 rounded-md opacity-60" />
        </div>
        <Skeleton className="h-10 w-44 rounded-xl" />
      </div>

      <ProjectListSkeleton />
    </div>
  );
}
