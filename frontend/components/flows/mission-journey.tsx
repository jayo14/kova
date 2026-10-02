import { MaterialIcon } from "@/components/shared/material-icon";

interface MissionStep {
  action: string;
  selector?: string | null;
  value?: string | null;
  credential_id?: string | null;
  description?: string | null;
}

interface MissionJourneyProps {
  steps: MissionStep[];
}

export function MissionJourney({ steps }: MissionJourneyProps) {
  if (!steps || steps.length === 0) return null;

  return (
    <section aria-label="Mission journey" className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-body-sm font-semibold text-foreground uppercase tracking-wider text-caption">
            Journey stages
          </h2>
          <p className="text-body-xs text-muted-foreground mt-0.5">
            High-level stages Kova accomplishes autonomously.
          </p>
        </div>
        <span className="inline-flex items-center rounded-full bg-secondary/60 px-2.5 py-0.5 text-caption font-medium text-muted-foreground">
          {steps.length} {steps.length === 1 ? "stage" : "stages"}
        </span>
      </div>

      <ol className="relative space-y-3 before:absolute before:left-3.5 before:top-3 before:bottom-3 before:w-[1px] before:bg-border/70">
        {steps.map((step, i) => {
          const stageNumber = String(i + 1).padStart(2, "0");
          const label = step.description ?? step.action;
          return (
            <li key={i} className="group relative flex items-start gap-3.5 pl-1">
              <span
                className="relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-border/80 bg-secondary/30 font-mono text-[11px] font-semibold text-muted-foreground group-first:border-primary/40 group-first:bg-primary/10 group-first:text-primary transition-colors"
                aria-hidden="true"
              >
                {stageNumber}
              </span>
              <div className="min-w-0 flex-1 pt-0.5">
                <p className="text-body-sm text-foreground/90 leading-snug">
                  {label}
                </p>
              </div>
            </li>
          );
        })}
      </ol>

      <div className="flex items-center gap-1.5 pt-1 text-caption text-muted-foreground/70">
        <MaterialIcon name="auto_awesome" size={13} className="text-primary/60 shrink-0" />
        <span>Kova handles DOM targets, selectors, and assertions dynamically.</span>
      </div>
    </section>
  );
}
