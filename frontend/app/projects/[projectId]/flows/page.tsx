import { redirect } from "next/navigation";

export default async function ProjectFlowsPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  redirect(`/flows?project=${projectId}`);
}
