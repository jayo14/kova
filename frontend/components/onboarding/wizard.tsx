"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { updateOnboardingStep } from "@/lib/api/onboarding";
import { createProject } from "@/lib/api/projects";
import { createCredential } from "@/lib/api/credentials";
import {
  createExplorationSession,
  streamExplorationEvents,
  type BackendExplorationSession,
} from "@/lib/api/exploration";
import { getFlows } from "@/lib/api/flows";
import { createExecution } from "@/lib/api/executions";

interface WizardProps {
  initialStep?: number;
  userName?: string;
}

export function OnboardingWizard({ initialStep = 0 }: WizardProps) {
  const router = useRouter();
  const [step, setStep] = useState<number>(initialStep >= 4 ? 0 : initialStep);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

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
  const [latestScreenshot, setLatestScreenshot] = useState<string | null>(null);
  const [discoveredFlowId, setDiscoveredFlowId] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Step 4 state
  const [validationRunning, setValidationRunning] = useState(false);
  const [executionId, setExecutionId] = useState<string | null>(null);
  const [executionStatus, setExecutionStatus] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const handleSkip = async () => {
    try {
      await updateOnboardingStep(4);
    } catch {
      // ignore
    }
    router.push("/dashboard");
  };

  const goToStep = async (newStep: number) => {
    setErrorMessage(null);
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
    setErrorMessage(null);

    const cleanBaseUrl = baseUrl.trim();
    if (!cleanBaseUrl.startsWith("http://") && !cleanBaseUrl.startsWith("https://")) {
      setErrorMessage("Please enter a valid URL starting with http:// or https://");
      setLoading(false);
      return;
    }

    try {
      const proj = await createProject({
        name: appName.trim(),
        baseUrl: cleanBaseUrl,
        description: "Created via onboarding wizard",
      });
      setProjectId(proj.id);
      await goToStep(1);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create project. Please verify the URL and try again.";
      setErrorMessage(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleStep2Submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setErrorMessage(null);

    try {
      if (testUser.trim() && testPassword.trim()) {
        await createCredential({
          projectId: projectId || undefined,
          name: envName.trim() || "Default",
          email: testUser.trim(),
          password: testPassword,
        });
      }
      await goToStep(2);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save credentials. Please check your inputs.";
      setErrorMessage(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleRunDiscovery = async () => {
    if (!baseUrl) return;
    setDiscoveryRunning(true);
    setErrorMessage(null);
    setDiscoveredPages([]);
    setLatestScreenshot(null);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const cleanBaseUrl = /^https?:\/\//i.test(baseUrl.trim())
        ? baseUrl.trim()
        : /^(?:localhost|127\.0\.0\.1)/i.test(baseUrl.trim())
        ? `http://${baseUrl.trim()}`
        : `https://${baseUrl.trim()}`;

      let session: BackendExplorationSession;
      try {
        session = await createExplorationSession(
          cleanBaseUrl,
          "Discover user routes, navigation flows, and interactive features"
        );
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Failed to start exploration session.";
        setErrorMessage(msg);
        setDiscoveryRunning(false);
        return;
      }

      // Add base path
      try {
        const parsed = new URL(cleanBaseUrl);
        setDiscoveredPages([parsed.pathname || "/"]);
      } catch {
        setDiscoveredPages(["/"]);
      }

      await streamExplorationEvents(
        session.id,
        (event) => {
          if (event.type === "page_loaded") {
            if (event.url || event.path) {
              const displayPath = event.path || (() => {
                try {
                  return new URL(event.url).pathname;
                } catch {
                  return event.url;
                }
              })();
              if (displayPath) {
                setDiscoveredPages((prev) =>
                  prev.includes(displayPath) ? prev : [...prev, displayPath]
                );
              }
            }
            if (event.screenshot) {
              setLatestScreenshot(event.screenshot);
            }
          } else if (event.type === "screenshot" && event.screenshot) {
            setLatestScreenshot(event.screenshot);
          } else if (event.type === "state_change") {
            if (event.state === "completed" || event.state === "ready" || event.state === "failed") {
              setDiscoveryRunning(false);
            }
          }
        },
        controller.signal
      );

      // Fetch flows associated with this project to prepare validation
      if (projectId) {
        try {
          const flows = await getFlows(projectId);
          if (flows.length > 0) {
            setDiscoveredFlowId(flows[0].id);
          }
        } catch {
          // ignore
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name !== "AbortError") {
        setErrorMessage((err as Error).message || "Discovery process encountered an issue.");
      }
    } finally {
      setDiscoveryRunning(false);
    }
  };

  const handleRunValidation = async () => {
    setValidationRunning(true);
    setErrorMessage(null);

    try {
      let targetFlowId = discoveredFlowId;
      if (!targetFlowId && projectId) {
        const flows = await getFlows(projectId);
        if (flows.length > 0) {
          targetFlowId = flows[0].id;
          setDiscoveredFlowId(targetFlowId);
        }
      }

      if (!targetFlowId) {
        setErrorMessage("No flow available to execute. You can proceed to dashboard and create a flow.");
        setValidationRunning(false);
        return;
      }

      const exec = await createExecution(targetFlowId);
      if (exec) {
        setExecutionId(exec.id);
        setExecutionStatus(exec.status || "running");
        // Direct user straight to real execution page
        router.push(`/executions/${exec.id}`);
      } else {
        setErrorMessage("Could not launch flow execution.");
        setValidationRunning(false);
      }
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to run validation execution.");
      setValidationRunning(false);
    }
  };

  const stepsList = [
    { title: "Connect App", icon: "language" },
    { title: "Credentials", icon: "vpn_key" },
    { title: "Discovery", icon: "hub" },
    { title: "Validation", icon: "verified" },
  ];

  const docsUrl = process.env.NEXT_PUBLIC_DOCS_URL || "/docs";
  const statusUrl = process.env.NEXT_PUBLIC_STATUS_URL || "/status";

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
        {errorMessage && (
          <div className="mb-6 p-4 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm flex items-start gap-2">
            <MaterialIcon name="error_outline" size={18} className="mt-0.5 shrink-0" />
            <span>{errorMessage}</span>
          </div>
        )}

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
                  Environment Name
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
                <PasswordInput
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
              <Button type="submit" disabled={loading} className="flex items-center gap-2">
                {loading ? "Saving..." : "Continue to Discovery"}
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
                  disabled={discoveryRunning}
                  className="flex items-center gap-2"
                >
                  <MaterialIcon name="play_arrow" size={16} />
                  {discoveryRunning ? "Exploring App..." : discoveredPages.length > 0 ? "Re-run Discovery" : "Start Discovery"}
                </Button>
              </div>

              {latestScreenshot && (
                <div className="mt-4 border border-border/60 rounded-xl overflow-hidden max-h-48 relative">
                  <div className="text-[10px] font-mono bg-black/60 text-white px-2 py-0.5 absolute top-2 left-2 z-10 rounded">
                    Live View
                  </div>
                  <Image
                    src={latestScreenshot}
                    alt="Discovered page preview"
                    width={640}
                    height={360}
                    unoptimized
                    className="w-full object-cover object-top max-h-48"
                  />
                </div>
              )}

              {discoveredPages.length > 0 && (
                <div className="pt-3 border-t border-border/40 space-y-2">
                  <div className="text-xs font-semibold text-muted-foreground">Discovered Endpoints ({discoveredPages.length}):</div>
                  <div className="flex flex-wrap gap-2 max-h-36 overflow-y-auto">
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
                    <MaterialIcon name={executionStatus ? "task_alt" : "sync"} size={24} className={executionStatus === "completed" ? "text-emerald-500" : ""} />
                  </div>
                  <div>
                    <h3 className="font-semibold text-sm">Baseline Validation Suite</h3>
                    <p className="text-xs text-muted-foreground">
                      {executionStatus ? `Execution ${executionStatus}` : "Executes critical flow with assertion verification"}
                    </p>
                  </div>
                </div>

                <Button
                  onClick={handleRunValidation}
                  disabled={validationRunning}
                  className="flex items-center gap-2"
                >
                  <MaterialIcon name="verified" size={16} />
                  {validationRunning ? "Launching Validation..." : executionId ? "Run Again" : "Run Validation"}
                </Button>
              </div>

              {executionId && (
                <div className="p-4 rounded-xl bg-primary/5 border border-primary/20 text-foreground space-y-2">
                  <div className="font-bold text-sm flex items-center gap-1.5">
                    <MaterialIcon name="check_circle" size={16} className="text-primary" />
                    Validation run launched: <span className="font-mono text-xs">{executionId}</span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Redirecting to execution trace...
                  </div>
                  <Button
                    size="sm"
                    onClick={() => router.push(`/executions/${executionId}`)}
                    className="mt-2 text-xs"
                  >
                    View Execution
                  </Button>
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
        <a href={docsUrl} target="_blank" rel="noreferrer" className="text-primary hover:underline">
          Documentation
        </a>{" "}
        or check the{" "}
        <a href={statusUrl} target="_blank" rel="noreferrer" className="text-primary hover:underline">
          System Status
        </a>
        .
      </div>
    </div>
  );
}
