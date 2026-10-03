"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Logo } from "@/components/shared/logo";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { createClient } from "@/lib/auth/client";
import type { User } from "@/lib/auth/custom";

const navLinks = [
  { label: "Product", href: "#product" },
  { label: "How it works", href: "#how-it-works" },
  { label: "Developers", href: "#developers" },
];

export function Navbar() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(({ data: { user } }) => {
      setUser(user);
      setLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event: any, session: any) => {
      setUser(session?.user ?? null);
    });

    return () => subscription.unsubscribe();
  }, []);

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/80 bg-background/85 backdrop-blur-md transition-all">
      <nav className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <div className="flex items-center gap-8">
          <Logo size="sm" />
          <div className="hidden items-center gap-6 md:flex">
            <Separator orientation="vertical" className="h-3.5 opacity-60" />
            {navLinks.map((link) => (
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

        <div className="hidden items-center gap-3 md:flex">
          {loading ? (
            <div className="h-8 w-20 animate-pulse rounded-lg bg-muted" />
          ) : user ? (
            <Button
              size="sm"
              onClick={() => router.push("/dashboard")}
              className="font-medium"
            >
              Dashboard
              <MaterialIcon name="arrow_forward" size={14} />
            </Button>
          ) : (
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => router.push("/auth/login")}
                className="text-muted-foreground hover:text-foreground"
              >
                Sign in
              </Button>
              <Button
                size="sm"
                onClick={() => router.push("/auth/signup")}
                className="font-medium"
              >
                Get started
              </Button>
            </>
          )}
        </div>

        {/* Mobile Navigation */}
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger
            render={
              <Button
                variant="ghost"
                size="icon-sm"
                className="md:hidden"
              />
            }
          >
            <MaterialIcon name="menu" size={20} />
            <span className="sr-only">Open menu</span>
          </SheetTrigger>
          <SheetContent side="right" showCloseButton={false} className="bg-background">
            <SheetHeader>
              <SheetTitle className="sr-only">Navigation</SheetTitle>
            </SheetHeader>
            <div className="flex flex-col gap-1 p-4">
              <div className="flex items-center justify-between pb-4 border-b border-border">
                <Logo size="sm" />
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => setOpen(false)}
                >
                  <MaterialIcon name="close" size={20} />
                  <span className="sr-only">Close menu</span>
                </Button>
              </div>

              <div className="flex flex-col gap-1 py-4">
                {navLinks.map((link) => (
                  <a
                    key={link.href}
                    href={link.href}
                    onClick={() => setOpen(false)}
                    className="rounded-lg px-3 py-2 text-body text-foreground transition-colors hover:bg-secondary/40"
                  >
                    {link.label}
                  </a>
                ))}
              </div>

              <Separator className="my-2" />

              <div className="flex flex-col gap-2 pt-2">
                {user ? (
                  <Button
                    className="w-full"
                    onClick={() => {
                      setOpen(false);
                      router.push("/dashboard");
                    }}
                  >
                    Dashboard
                    <MaterialIcon name="arrow_forward" size={16} />
                  </Button>
                ) : (
                  <>
                    <Button
                      variant="outline"
                      className="w-full"
                      onClick={() => {
                        setOpen(false);
                        router.push("/auth/login");
                      }}
                    >
                      Sign in
                    </Button>
                    <Button
                      className="w-full"
                      onClick={() => {
                        setOpen(false);
                        router.push("/auth/signup");
                      }}
                    >
                      Get started
                    </Button>
                  </>
                )}
              </div>
            </div>
          </SheetContent>
        </Sheet>
      </nav>
    </header>
  );
}
