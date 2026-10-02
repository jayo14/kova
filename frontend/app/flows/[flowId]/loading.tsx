import { MissionDetailSkeleton } from "@/components/flows/mission-skeleton";

export default function FlowDetailLoading() {
  return (
    <div className="w-full max-w-4xl mx-auto px-6 py-10 md:py-14">
      <MissionDetailSkeleton />
    </div>
  );
}
