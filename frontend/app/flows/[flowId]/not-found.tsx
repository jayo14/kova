import Link from "next/link";
import { MaterialIcon } from "@/components/shared/material-icon";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function FlowNotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center px-6 py-24 text-center">
      <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-secondary/50 text-muted-foreground">
        <MaterialIcon name="error" size={24} />
      </div>
      <h2 className="text-display sm:text-[2rem] font-bold text-foreground mb-2">
        Mission not found
      </h2>
      <p className="text-body-sm text-muted-foreground mb-6 max-w-sm leading-relaxed">
        This mission doesn&apos;t exist or you don&apos;t have access to it in this organization.
      </p>
      <Link
        href="/flows"
        className={cn(
          buttonVariants({ variant: "default" }),
          "inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-body-sm font-medium"
        )}
      >
        <MaterialIcon name="arrow_back" size={16} />
        <span>Back to missions</span>
      </Link>
    </div>
  );
}
