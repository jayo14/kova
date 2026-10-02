import { MaterialIcon } from "@/components/shared/material-icon";
import type { ExploreState } from "@/lib/types";
import { cn } from "@/lib/utils";

interface AgentStatusProps {
  state: ExploreState;
  url?: string;
  className?: string;
}

interface StateConfig {
  icon: string;
  label: string;
  description: string;
}

const stateConfig: Record<ExploreState, StateConfig> = {
  idle: {
    icon: "search",
    label: "Ready to explore",
    description: "Enter a website to begin",
  },
  connecting: {
    icon: "cached",
    label: "Connecting",
    description: "Preparing an isolated session",
  },
  loading: {
    icon: "downloading",
    label: "Loading page",
    description: "Fetching the target page",
  },
  validating_page: {
    icon: "verified",
    label: "Validating page",
    description: "Checking if the page is accessible",
  },
  exploring: {
    icon: "explore",
    label: "Exploring",
    description: "Kova is navigating the product",
  },
  understanding: {
    icon: "psychology",
    label: "Understanding",
    description: "Kova is mapping the interface",
  },
  auth_required: {
    icon: "lock",
    label: "Authentication required",
    description: "This product requires an account",
  },
  authenticating: {
    icon: "login",
    label: "Signing in",
    description: "Authenticating test session",
  },
  asking: {
    icon: "help",
    label: "Needs your input",
    description: "Kova has a quick question to continue",
  },
  discovering: {
    icon: "hub",
    label: "Discovering journeys",
    description: "Mapping core workflows and entry points",
  },
  planning: {
    icon: "route",
    label: "Planning missions",
    description: "Synthesizing candidate journeys",
  },
  ready: {
    icon: "check_circle",
    label: "Ready",
    description: "Kova identified useful journeys",
  },
  executing: {
    icon: "play_circle",
    label: "Executing mission",
    description: "Running the test scenario",
  },
  completed: {
    icon: "check_circle",
    label: "Completed",
    description: "Mission finished successfully",
  },
  mission_selected: {
    icon: "play_circle",
    label: "Preparing mission",
    description: "Setting up test environment",
  },
  mission_created: {
    icon: "play_circle",
    label: "Preparing mission",
    description: "Setting up test environment",
  },
  failed: {
    icon: "error",
    label: "Exploration failed",
    description: "Kova couldn't finish exploring this product",
  },
  cancelled: {
    icon: "stop",
    label: "Exploration stopped",
    description: "Exploration was cancelled",
  },
};

export function AgentStatus({ state, url, className }: AgentStatusProps) {
  const config = stateConfig[state] || stateConfig.idle;

  return (
    <div className={cn("text-center select-none", className)}>
      <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-secondary/40 border border-border">
        <MaterialIcon
          name={config.icon}
          size={20}
          className={cn(
            state === "ready"
              ? "text-emerald-600"
              : state === "failed"
                ? "text-destructive"
                : state === "cancelled"
                  ? "text-muted-foreground"
                  : ["connecting", "loading", "validating_page"].includes(state)
                    ? "text-primary animate-spin"
                    : "text-primary"
          )}
        />
      </div>

      <p className="text-body font-medium text-foreground mb-0.5">
        {config.label}
      </p>
      <p className="text-caption text-muted-foreground max-w-xs mx-auto">
        {config.description}
      </p>

      {url && (
        <p className="text-mono text-[11px] text-muted-foreground/60 mt-2 truncate max-w-sm mx-auto">
          {url}
        </p>
      )}
    </div>
  );
}
