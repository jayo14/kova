import { MaterialIcon } from "@/components/shared/material-icon";
import type { DiscoveryItem } from "@/lib/types";
import { cn } from "@/lib/utils";

interface AgentDiscoveryProps {
  discoveries: DiscoveryItem[];
  className?: string;
}

export function AgentDiscovery({ discoveries, className }: AgentDiscoveryProps) {
  if (discoveries.length === 0) return null;

  return (
    <div className={cn("text-center", className)}>
      <p className="text-body-lg font-medium text-foreground mb-2">
        Here&apos;s what I found.
      </p>
      <p className="text-body-sm text-muted-foreground mb-6">
        I explored the product and identified these areas.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-lg mx-auto text-left">
        {discoveries.map((d) => (
          <div
            key={d.label}
            className="flex items-start gap-3 rounded-lg border border-border px-4 py-3"
          >
            <MaterialIcon
              name="check_circle"
              size={16}
              className="shrink-0 mt-0.5 text-primary"
            />
            <div>
              <p className="text-body-sm font-medium text-foreground">
                {d.label}
              </p>
              <p className="text-caption">{d.description}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
