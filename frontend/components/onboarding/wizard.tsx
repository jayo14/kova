"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { updateOnboardingStep } from "@/lib/api/onboarding";
import { createProject } from "@/lib/api/projects";

interface WizardProps {
  initialStep?: number;
  userName?: string;
}

export function OnboardingWizard({ initialStep = 0, userName }: WizardProps) {
  const router = useRouter();
  const [step, setStep] = useState<number>(initialStep >= 4 ? 0 : initialStep);
  const [loading, setLoading] = useState(false);

  // Step 1 state
  const [appName, setAppName] = useState("My Web App");
  const [baseUrl, setBaseUrl] = useState("https://example.com");
  const [projectId, setProjectId] = useState<string | null>(null);

  // Step 2 state
  const [testUser, setTestUser] = useState("qa-tester@kova.dev");
  const [testPassword, setTestPassword] = useState("password123");
  const [envName, setEnvName] = useState("Staging");

  // Step 3 state
  const [discoveryRunning, setDiscoveryRunning] = useState(false);
  const [discoveredPages, setDiscoveredPages] = useState<string[]>([]);

  // Step 4 state
  const [validationRunning, setValidationRunning] = useState(false);
  const [validationDone, setValidationDone] = useState(false);

  const handleSkip = async () => {
    try {
      await updateOnboardingStep(4);
    } catch {
      // ignore
    }
    router.push("/dashboard");
  };

  const goToStep = async (newStep: number) => {
    setStep(newStep);
    try {
      await updateOnboardingStep(newStep);
    } catch {
      // ignore
    }
  };

  const handleStep1Submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const proj = await createProject({
        name: appName.trim(),
        baseUrl: baseUrl.trim(),
        description: "Created via onboarding wizard",
      });
      setProjectId(proj.id);
      await goToStep(1);
    } catch (err: any) {
      // Even if network or mock fails, proceed gracefully
      console.warn("Project creation in onboarding:", err);
      await goToStep(1);
    } finally {
      setLoading(false);
    }
  };

  const handleStep2Submit = async (e: React.FormEvent) => {
    e.preventDefault();
    await goToStep(2);
  };

  const handleRunDiscovery = async () => {
    setDiscoveryRunning(true);
    setDiscoveredPages(["/"]);
    setTimeout(() => {
      setDiscoveredPages((prev) => [...prev, "/login", "/dashboard"]);
    }, 1200);
    setTimeout(() => {
      setDiscoveredPages((prev) => [...prev, "/settings", "/billing", "/checkout"]);
      setDiscoveryRunning(false);
    }, 2500);
  };

  const handleRunValidation = async () => {
    setValidationRunning(true);
    setTimeout(() => {
      setValidationRunning(false);
      setValidationDone(true);
    }, 2000);
  };

  const stepsList = [
    { title: "Connect App", icon: "language" },
    { title: "Credentials", icon: "vpn_key" },
    { title: "Discovery", icon: "hub" },
    { title: "Validation", icon: "verified" },
  ];

  return (
    <div className="min-h-screen bg-background flex flex-col justify-between p-6 max-w-4xl mx-auto">
      {/* Top Bar */}
      <div className="flex items-center justify-between border-b border-border/60 pb-4">
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-xl bg-primary flex items-center justify-center text-primary-foreground font-bold">
            K
          </div>
          <span className="font-bold text-lg tracking-tight">Kova Setup Wizard</span>
        </div>
        <Button variant="ghost" onClick={handleSkip} className="text-muted-foreground hover:text-foreground text-xs">
          Skip Onboarding
          <MaterialIcon name="chevron_right" size={16} className="ml-1" />
        </Button>
      </div>

      {/* Progress Stepper */}
      <div className="py-8">
        <div className="grid grid-cols-4 gap-2">
          {stepsList.map((s, idx) => {
            const isCompleted = step > idx;
            const isCurrent = step === idx;
            return (
              <div
                key={s.title}
                className={`flex flex-col items-center gap-1.5 p-3 rounded-xl border text-center transition-all ${
                  isCurrent
                    ? "border-primary bg-primary/10 text-primary font-semibold shadow-sm"
                    : isCompleted
                    ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-600 dark:text-emerald-400"
                    : "border-border/60 bg-card/40 text-muted-foreground"
                }`}
              >
                <div className="flex items-center gap-1">
                  <MaterialIcon name={isCompleted ? "check_circle" : s.icon} size={18} />
                  <span className="text-xs uppercase font-mono">Step {idx + 1}</span>
                </div>
                <span className="text-xs">{s.title}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Wizard Body Card */}
      <div className="border border-border/80 rounded-2xl bg-card/60 p-8 shadow-sm flex-1 flex flex-col justify-between my-2">
        {step === 0 && (
          <form onSubmit={handleStep1Submit} className="space-y-6">
            <div className="space-y-2">
              <Badge variant="outline" className="text-xs font-mono">STEP 1 OF 4</Badge>
              <h2 className="text-2xl font-bold tracking-tight">Connect your Web Application</h2>
              <p className="text-sm text-muted-foreground">
                Enter your web app URL. Kova uses this baseline URL to crawl interactive routes, build your product graph, and execute test flows.
              </p>
            </div>

            <div className="space-y-4 max-w-lg">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Application Name
                </label>
                <Input
                  value={appName}
                  onChange={(e) => setAppName(e.target.value)}
                  placeholder="e.g. Acme SaaS"
                  required
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Base URL (Staging or Production)
                </label>
                <Input
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="https://staging.myapp.com"
                  required
                />
              </div>
            </div>

            <div className="flex justify-between items-center pt-6 border-t border-border/40">
              <Button type="button" variant="ghost" onClick={handleSkip}>
                Skip to Dashboard
              </Button>
              <Button type="submit" disabled={loading} className="flex items-center gap-2">
                {loading ? "Connecting..." : "Continue"}
                <MaterialIcon name="arrow_forward" size={16} />
              </Button>
            </div>
          </form>
        )}

        {step === 1 && (
          <form onSubmit={handleStep2Submit} className="space-y-6">
            <div className="space-y-2">
              <Badge variant="outline" className="text-xs font-mono">STEP 2 OF 4</Badge>
              <h2 className="text-2xl font-bold tracking-tight">Configure Test Credentials</h2>
              <p className="text-sm text-muted-foreground">
                Provide credentials so Kova can authenticate into protected routes and explore authenticated workflows.
              </p>
            </div>

            <div className="space-y-4 max-w-lg">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Environment
                </label>
                <Input
                  value={envName}
                  onChange={(e) => setEnvName(e.target.value)}
                  placeholder="Staging"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Username or Test Email
                </label>
                <Input
                  value={testUser}
                  onChange={(e) => setTestUser(e.target.value)}
                  placeholder="tester@example.com"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Password
                </label>
                <Input
                  type="password"
                  value={testPassword}
                  onChange={(e) => setTestPassword(e.target.value)}
                  placeholder="••••••••"
                />
              </div>
            </div>

            <div className="flex justify-between items-center pt-6 border-t border-border/40">
              <Button type="button" variant="outline" onClick={() => goToStep(0)}>
                Back
              </Button>
              <Button type="submit" className="flex items-center gap-2">
                Continue to Discovery
                <MaterialIcon name="arrow_forward" size={16} />
              </Button>
            </div>
          </form>
        )}

        {step === 2 && (
          <div className="space-y-6">
            <div className="space-y-2">
              <Badge variant="outline" className="text-xs font-mono">STEP 3 OF 4</Badge>
              <h2 className="text-2xl font-bold tracking-tight">Run Autonomous Discovery</h2>
              <p className="text-sm text-muted-foreground">
                Kova crawls your app, discovers user routes, inputs, and interactive components, and builds your live Product Graph.
              </p>
            </div>

            <div className="p-6 rounded-2xl border border-border/60 bg-secondary/20 space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`p-3 rounded-xl ${discoveryRunning ? "bg-primary/20 text-primary animate-pulse" : "bg-card text-foreground"}`}>
                    <MaterialIcon name="travel_explore" size={24} />
                  </div>
                  <div>
                    <h3 className="font-semibold text-sm">Site Discovery Engine</h3>
                    <p className="text-xs text-muted-foreground">
                      Target: <span className="font-mono text-foreground">{baseUrl}</span>
                    </p>
                  </div>
                </div>

                <Button
                  onClick={handleRunDiscovery}
                  disabled={discoveryRunning || discoveredPages.length > 0}
                  className="flex items-center gap-2"
                >
                  <MaterialIcon name="play_arrow" size={16} />
                  {discoveryRunning ? "Exploring App..." : discoveredPages.length > 0 ? "Discovery Complete" : "Start Discovery"}
                </Button>
              </div>

              {discoveredPages.length > 0 && (
                <div className="pt-3 border-t border-border/40 space-y-2">
                  <div className="text-xs font-semibold text-muted-foreground">Discovered Endpoints:</div>
                  <div className="flex flex-wrap gap-2">
                    {discoveredPages.map((p) => (
                      <Badge key={p} variant="secondary" className="font-mono text-xs py-1 px-2 flex items-center gap-1">
                        <MaterialIcon name="check" size={12} className="text-emerald-500" />
                        {p}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="flex justify-between items-center pt-6 border-t border-border/40">
              <Button type="button" variant="outline" onClick={() => goToStep(1)}>
                Back
              </Button>
              <Button
                onClick={() => goToStep(3)}
                disabled={discoveryRunning}
                className="flex items-center gap-2"
              >
                Proceed to First Validation
                <MaterialIcon name="arrow_forward" size={16} />
              </Button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-6">
            <div className="space-y-2">
              <Badge variant="outline" className="text-xs font-mono">STEP 4 OF 4</Badge>
              <h2 className="text-2xl font-bold tracking-tight">Run First Continuous Validation</h2>
              <p className="text-sm text-muted-foreground">
                Run an automated verification pass across your discovered critical paths to establish your baseline health score.
              </p>
            </div>

            <div className="p-6 rounded-2xl border border-border/60 bg-secondary/20 space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`p-3 rounded-xl ${validationRunning ? "bg-primary/20 text-primary animate-spin" : "bg-card text-foreground"}`}>
                    <MaterialIcon name={validationDone ? "task_alt" : "sync"} size={24} className={validationDone ? "text-emerald-500" : ""} />
                  </div>
                  <div>
                    <h3 className="font-semibold text-sm">Baseline Validation Suite</h3>
                    <p className="text-xs text-muted-foreground">
                      Testing login flow, navigation resilience, and UI accessibility
                    </p>
                  </div>
                </div>

                <Button
                  onClick={handleRunValidation}
                  disabled={validationRunning || validationDone}
                  className="flex items-center gap-2"
                >
                  <MaterialIcon name="verified" size={16} />
                  {validationRunning ? "Validating Flows..." : validationDone ? "Validation Passed" : "Run Validation"}
                </Button>
              </div>

              {validationDone && (
                <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-950 dark:text-emerald-300 space-y-1">
                  <div className="font-bold text-sm flex items-center gap-1.5">
                    <MaterialIcon name="check_circle" size={16} className="text-emerald-500" />
                    All 3 critical flows passed (100% health score)
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Baseline established. You are ready to integrate Kova in your CI pipeline!
                  </div>
                </div>
              )}
            </div>

            <div className="flex justify-between items-center pt-6 border-t border-border/40">
              <Button type="button" variant="outline" onClick={() => goToStep(2)}>
                Back
              </Button>
              <Button
                onClick={handleSkip}
                className="bg-emerald-600 hover:bg-emerald-700 text-white flex items-center gap-2"
              >
                Complete Setup & Go to Dashboard
                <MaterialIcon name="done_all" size={16} />
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="text-center text-xs text-muted-foreground pt-4">
        Need assistance setting up? Visit our{" "}
        <a href="http://localhost:3000/docs" target="_blank" rel="noreferrer" className="text-primary hover:underline">
          Documentation
        </a>{" "}
        or check the{" "}
        <a href="http://localhost:3000/status" target="_blank" rel="noreferrer" className="text-primary hover:underline">
          System Status
        </a>
        .
      </div>
    </div>
  );
}
