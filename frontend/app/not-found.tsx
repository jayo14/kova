import type { Metadata } from "next";
import Link from "next/link";
import { Logo } from "@/components/shared/logo";
import { MaterialIcon } from "@/components/shared/material-icon";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "404: Page Not Found | Kova",
  description: "The page you are looking for could not be found.",
};

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground antialiased selection:bg-primary/10 selection:text-primary">
      {/* Top Header */}
      <header className="border-b border-border/80 bg-background/80 backdrop-blur-md sticky top-0 z-50">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
          <Link href="/" className="flex items-center gap-2 group transition-opacity hover:opacity-90" aria-label="Kova home">
            <Logo size="sm" />
          </Link>
          <Link
            href="/dashboard"
            className="text-body-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            Dashboard
          </Link>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 flex items-center justify-center px-6 py-16 relative overflow-hidden">
        {/* Subtle background ambient glow */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-40 dark:opacity-20"
        >
          <div className="h-[360px] w-[360px] rounded-full bg-primary/15 blur-3xl filter" />
        </div>

        <div className="relative z-10 w-full max-w-md text-center animate-in fade-in zoom-in-95 duration-300">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-3.5 py-1 text-caption font-medium text-primary mb-6">
            <span className="size-1.5 rounded-full bg-primary animate-pulse" />
            404 Error
          </div>

          {/* Icon / Visual Anchor */}
          <div className="mx-auto mb-6 flex size-16 items-center justify-center rounded-2xl border border-border bg-card shadow-xs">
            <MaterialIcon
              name="explore_off"
              size={32}
              className="text-primary"
            />
          </div>

          {/* Heading */}
          <h1 className="text-h1 font-bold text-foreground tracking-tight mb-3">
            Page not found
          </h1>

          {/* Description */}
          <p className="text-body-sm text-muted-foreground leading-relaxed mb-8 max-w-sm mx-auto">
            The page you are looking for doesn&apos;t exist, has been moved, or the link may be broken.
          </p>

          {/* Call-to-actions */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link
              href="/"
              className={cn(
                buttonVariants({ variant: "default", size: "lg" }),
                "w-full sm:w-auto inline-flex items-center justify-center gap-2 rounded-xl px-6 py-2.5 text-body-sm font-medium shadow-sm transition-all"
              )}
            >
              <MaterialIcon name="home" size={18} />
              <span>Back to home</span>
            </Link>

            <Link
              href="/dashboard"
              className={cn(
                buttonVariants({ variant: "outline", size: "lg" }),
                "w-full sm:w-auto inline-flex items-center justify-center gap-2 rounded-xl px-5 py-2.5 text-body-sm font-medium transition-all"
              )}
            >
              <MaterialIcon name="dashboard" size={18} />
              <span>Go to dashboard</span>
            </Link>
          </div>

          {/* Quick Helpful Links */}
          <div className="mt-12 pt-8 border-t border-border/60">
            <p className="text-caption text-muted-foreground mb-3 font-medium">
              Helpful destinations
            </p>
            <div className="flex flex-wrap items-center justify-center gap-4 text-body-sm text-muted-foreground">
              <Link
                href="/projects"
                className="transition-colors hover:text-foreground hover:underline underline-offset-4"
              >
                Products
              </Link>
              <span className="text-border">•</span>
              <Link
                href="/explore"
                className="transition-colors hover:text-foreground hover:underline underline-offset-4"
              >
                Explore
              </Link>
              <span className="text-border">•</span>
              <Link
                href="/auth/login"
                className="transition-colors hover:text-foreground hover:underline underline-offset-4"
              >
                Sign in
              </Link>
            </div>
          </div>
        </div>
      </main>

      {/* Subtle Footer */}
      <footer className="border-t border-border/60 py-6 text-center text-caption text-muted-foreground">
        <div className="mx-auto max-w-6xl px-6">
          <p>© {new Date().getFullYear()} Kova. Autonomous software-use platform.</p>
        </div>
      </footer>
    </div>
  );
}
