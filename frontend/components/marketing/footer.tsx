import { Logo } from "@/components/shared/logo";
import { Separator } from "@/components/ui/separator";

const productLinks = [
  { label: "Product", href: "#product" },
  { label: "How it works", href: "#how-it-works" },
  { label: "Developers", href: "#developers" },
];

const authLinks = [
  { label: "Sign in", href: "/auth/login" },
  { label: "Get started", href: "/auth/signup" },
];

export function Footer() {
  return (
    <footer className="border-t border-border bg-background">
      <div className="mx-auto max-w-6xl px-6 py-14">
        <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-10">
          <div>
            <Logo size="sm" />
            <p className="text-body-sm text-muted-foreground mt-3 max-w-xs leading-relaxed">
              An autonomous agent for using software.
            </p>
          </div>

          <div className="flex gap-14 sm:gap-16">
            <div>
              <span className="text-label text-foreground font-semibold block mb-3">
                Navigation
              </span>
              <div className="flex flex-col gap-2.5">
                {productLinks.map((link) => (
                  <a
                    key={link.href}
                    href={link.href}
                    className="text-body-sm text-muted-foreground transition-colors hover:text-foreground"
                  >
                    {link.label}
                  </a>
                ))}
              </div>
            </div>

            <div>
              <span className="text-label text-foreground font-semibold block mb-3">
                Account
              </span>
              <div className="flex flex-col gap-2.5">
                {authLinks.map((link) => (
                  <a
                    key={link.href}
                    href={link.href}
                    className="text-body-sm text-muted-foreground transition-colors hover:text-foreground"
                  >
                    {link.label}
                  </a>
                ))}
              </div>
            </div>
          </div>
        </div>

        <Separator className="my-10" />

        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 text-caption text-muted-foreground">
          <p>&copy; {new Date().getFullYear()} Kova. All rights reserved.</p>
          <p className="font-mono text-[0.75rem]">Autonomous browser software use</p>
        </div>
      </div>
    </footer>
  );
}
