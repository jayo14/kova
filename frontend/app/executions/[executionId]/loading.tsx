import { ExecutionDetailSkeleton } from "@/components/executions/execution-skeleton";

export default function ExecutionDetailLoading() {
  return (
    <div className="w-full max-w-5xl mx-auto px-6 py-10 md:py-14">
      <ExecutionDetailSkeleton />
    </div>
  );
}
