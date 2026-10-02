import { Logo } from "@/components/shared/logo";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

export function Header() {
  return (
    <header className="sticky top-0 z-50 w-full border-b border-border bg-background/80 backdrop-blur-sm">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <div className="flex items-center gap-6">
          <Logo size="sm" />
          <Separator orientation="vertical" className="h-5" />
          <nav className="flex items-center gap-1">
            <Button variant="ghost" size="sm" className="text-muted-foreground">
              <MaterialIcon name="language" size={18} />
              Explore
            </Button>
            <Button variant="ghost" size="sm" className="text-muted-foreground">
              <MaterialIcon name="terminal" size={18} />
              Runs
            </Button>
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon-sm">
            <MaterialIcon name="settings" size={18} />
          </Button>
          <Button variant="ghost" size="icon-sm">
            <MaterialIcon name="person" size={18} />
          </Button>
        </div>
      </div>
    </header>
  );
}
