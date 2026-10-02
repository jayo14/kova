import { cn } from "@/lib/utils";

interface MaterialIconProps {
  name: string;
  className?: string;
  size?: number;
  filled?: boolean;
  "aria-hidden"?: boolean;
  "aria-label"?: string;
}

export function MaterialIcon({
  name,
  className,
  size = 24,
  filled = false,
  "aria-hidden": ariaHidden = true,
  "aria-label": ariaLabel,
}: MaterialIconProps) {
  return (
    <span
      className={cn("material-symbols-rounded", className)}
      style={{
        fontSize: size,
        fontVariationSettings: filled
          ? '"FILL" 1, "wght" 400, "GRAD" 0, "opsz" 24'
          : '"FILL" 0, "wght" 400, "GRAD" 0, "opsz" 24',
      }}
      aria-hidden={ariaHidden}
      role={ariaLabel ? "img" : undefined}
      aria-label={ariaLabel}
    >
      {name}
    </span>
  );
}
