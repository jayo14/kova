"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  AgentShell,
  AgentBrowserViewport,
  AgentActivity,
  AgentStatus,
  AgentQuestion,
  MissionSuggestions,
} from "@/components/agent";
import { ScreenshotGallery } from "@/components/agent/screenshot-gallery";
import { KovaInput, type KovaIntent } from "@/components/shared/kova-input";
import { Button } from "@/components/ui/button";
import { MaterialIcon } from "@/components/shared/material-icon";
import { Logo } from "@/components/shared/logo";
import {
  startExploration,
  submitCredential,
  answerQuestion,
  cancelExploration,
  createAccount,
  syncSessionState,
} from "@/lib/api/exploration";
import { createMission } from "@/lib/api/missions";
import { createExecution, runBatchExecutions } from "@/lib/api/executions";
import { createProject, getProjects } from "@/lib/api/projects";
import { useExploreMachine } from "./explore-state-machine";
import type { AuthChoice } from "@/components/agent/auth-choice-dialog";
import { extractProjectName, normalizeHostname } from "@/lib/agent/input-parser";
import type { ExplorationEvent } from "@/lib/types";

const SCREENSHOT_STATES = new Set([
  "connecting", "loading", "validating_page", "exploring",
  "authenticating", "discovering", "executing",
]);

export function ExplorePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialUrl = searchParams.get("url") || "";
  const initialIntent = searchParams.get("intent") || undefined;
  const initialSessionId = searchParams.get("sessionId") || "";
  const projectContextId = searchParams.get("projectId") || null;

  const {
    state,
    start,
    transition,
    addActivity,
    setAuthRequired,
    setAuthMode,
    setQuestion,
    setDiscoveries,
    setMissions,
    updateMission,
    setMissionCreated,
    addScreenshot,
    setPage,
    fail,
    cancel,
    reset,
  } = useExploreMachine(initialUrl, initialIntent);

  const [credentialError, setCredentialError] = useState<string | null>(null);
  const [credentialLoading, setCredentialLoading] = useState(false);
  const [resolvedProjectId, setResolvedProjectId] = useState<string | null>(projectContextId);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [galleryIndex, setGalleryIndex] = useState(0);
  const [showMissionsDialog, setShowMissionsDialog] = useState(true);

  useEffect(() => {
    if (state.state === "ready" && state.missions.length > 0) {
      setShowMissionsDialog(true);
    }
  }, [state.state, state.missions.length]);

  const abortRef = useRef<AbortController | null>(null);
  const startedUrlRef = useRef<string | null>(null);

  const handleEvent = useCallback(
    (event: ExplorationEvent) => {
      switch (event.type) {
        case "started":
          break;
        case "progress":
          addActivity(event.activity);
          break;
        case "state_change":
          transition(event.state);
          break;
        case "screenshot":
          addScreenshot(event.screenshot, "Playwright snapshot");
          break;
        case "page_loaded":
          setPage(event.url, event.title, event.path, event.screenshot);
          if (event.screenshot) {
            addScreenshot(event.screenshot, event.title || "Page loaded");
          }
          break;
        case "auth_required":
          setAuthRequired(event.request);
          break;
        case "question":
          setQuestion(event.question);
          break;
        case "discovery":
          setDiscoveries(event.discoveries);
          break;
        case "missions":
          setMissions(event.missions, event.recommendation);
          break;
        case "error":
          // Auth errors stay in auth_required state with error message
          // Fatal errors transition to failed state
          if (state.state === "authenticating" || state.state === "auth_required") {
            setCredentialError(event.message);
            transition("auth_required");
          } else {
            fail(event.message);
          }
          break;
      }
    },
    [addActivity, transition, addScreenshot, setPage, setAuthRequired, setQuestion, setDiscoveries, setMissions, fail, state.state]
  );

  const handleEventRef = useRef(handleEvent);
  handleEventRef.current = handleEvent;

  // Auto-start or recover exploration session
  useEffect(() => {
    if (initialSessionId) {
      if (startedUrlRef.current === initialSessionId) return;
      startedUrlRef.current = initialSessionId;
      syncSessionState(initialSessionId, (ev) => handleEventRef.current(ev)).catch((err) => {
        console.error("Failed to sync session:", err);
      });
      return;
    }

    if (!initialUrl) return;
    if (startedUrlRef.current === initialUrl) return;
    startedUrlRef.current = initialUrl;

    const controller = new AbortController();
    abortRef.current = controller;

    startExploration(
      initialUrl,
      initialIntent,
      (ev) => handleEventRef.current(ev),
      controller.signal
    )
      .then((sessionId) => {
        if (typeof window !== "undefined" && window.location) {
          const nextParams = new URLSearchParams(window.location.search);
          nextParams.set("sessionId", sessionId);
          window.history.replaceState(null, "", `?${nextParams.toString()}`);
        }
      })
      .catch((err) => {
        if (err?.name !== "AbortError") {
          console.error("Exploration error:", err);
        }
      });

    return () => {
      controller.abort();
    };
  }, [initialUrl, initialIntent, initialSessionId]);

  const handleSubmit = (intent: KovaIntent) => {
    const submittedUrl = intent.url || "";
    if (!submittedUrl) return;

    if (startedUrlRef.current === submittedUrl && state.state !== "idle" && state.state !== "failed" && state.state !== "cancelled") {
      return;
    }

    abortRef.current?.abort();

    const goal = intent.goal || intent.instruction;

    const query = new URLSearchParams();
    query.set("url", submittedUrl);
    if (goal) {
      query.set("intent", goal);
    }
    router.push(`/explore?${query.toString()}`, { scroll: false });

    const controller = new AbortController();
    abortRef.current = controller;
    startedUrlRef.current = submittedUrl;

    startExploration(
      submittedUrl,
      goal,
      (ev) => handleEventRef.current(ev),
      controller.signal
    ).catch((err) => {
      if (err?.name !== "AbortError") {
        console.error("Exploration error:", err);
      }
    });
  };

  const handleCredentialSubmit = async (email: string, password: string) => {
    setCredentialLoading(true);
    setCredentialError(null);

    try {
      const controller = new AbortController();
      abortRef.current = controller;
      // submitCredential no longer throws on auth failure —
      // errors arrive via events (auth.failed → error event)
      await submitCredential(email, password, handleEvent, controller.signal);
    } catch (err) {
      // Only catch actual infrastructure errors (network, server down)
      const message = err instanceof Error ? err.message : "Could not reach the server.";
      setCredentialError(message);
      transition("auth_required");
    } finally {
      setCredentialLoading(false);
    }
  };

  const handleAuthChoice = async (choice: AuthChoice, details?: { email: string; password: string }) => {
    if (choice === "manual_login" && details) {
      setAuthMode("manual_login");
      await handleCredentialSubmit(details.email, details.password);
      return;
    }

    if (choice === "create_account") {
      setAuthMode("creating_account");
      setCredentialLoading(true);
      setCredentialError(null);

      try {
        const controller = new AbortController();
        abortRef.current = controller;
        await createAccount(
          details?.email,
          details?.password,
          handleEvent,
          controller.signal
        );
      } catch (err) {
        const message = err instanceof Error ? err.message : "Could not create account.";
        setCredentialError(message);
        setAuthMode("choice");
        transition("auth_required");
      } finally {
        setCredentialLoading(false);
      }
    }
  };

  const handleAnswerQuestion = async (selectedOptionId: string) => {
    if (!state.question) return;

    const controller = new AbortController();
    abortRef.current = controller;

    await answerQuestion(
      state.question.id,
      selectedOptionId,
      handleEvent,
      controller.signal
    );
  };

  const handleStop = () => {
    abortRef.current?.abort();
    cancel();
    cancelExploration(handleEvent);
  };

  const handleUrlChange = useCallback((url: string, path: string) => {
    setPage(url, undefined, path, undefined);
  }, [setPage]);

  const handleBack = () => {
    abortRef.current?.abort();
    reset();
    router.push("/explore", { scroll: false });
  };

  const handleThumbnailClick = useCallback((index: number) => {
    setGalleryIndex(index);
    setGalleryOpen(true);
  }, []);

  const handleRunMissions = async (missionIds: string[], parallel: boolean = false) => {
    transition("mission_created");

    const selectedMissions = state.missions.filter((m) => missionIds.includes(m.id));
    const targetUrl = state.url || initialUrl;
    const hostname = (() => {
      try {
        return new URL(targetUrl).hostname;
      } catch {
        return targetUrl.replace(/^https?:\/\//, "").split("/")[0] || "product";
      }
    })();

    let projectId = resolvedProjectId;

    if (!projectId) {
      try {
        const existingProjects = await getProjects();
        const currentNormalizedHost = normalizeHostname(hostname);
        const existing = existingProjects.find((p) => {
          try {
            return normalizeHostname(new URL(p.baseUrl).hostname) === currentNormalizedHost;
          } catch {
            return false;
          }
        });

        if (existing) {
          projectId = existing.id;
        } else {
          const projectName = extractProjectName(hostname);

          const project = await createProject({
            name: projectName,
            description: `Auto-created from Kova explore: ${targetUrl}`,
            baseUrl: targetUrl,
          });
          projectId = project.id;
        }
      } catch {
        fail("Could not create or find a project. Check that the backend is running and try again.");
        return;
      }
    }

    setResolvedProjectId(projectId);
    setMissionCreated(projectId);

    const createdMissions = [];
    const missionErrors: string[] = [];
    for (const suggested of selectedMissions) {
      try {
        const m = await createMission({
          projectId,
          projectName: hostname,
          projectUrl: targetUrl,
          name: suggested.title,
          description: suggested.description,
          persona: suggested.persona ?? undefined,
          objective: suggested.objective || suggested.description,
          steps: suggested.steps,
          // Structured condition passed through verbatim; undefined (not null)
          // when absent so createMission omits it rather than nulling a valid one.
          successCondition: suggested.successCondition ?? undefined,
        });
        createdMissions.push(m);
      } catch (e) {
        missionErrors.push(suggested.title || "Unnamed mission");
      }
    }

    if (missionErrors.length > 0 && createdMissions.length === 0) {
      fail(`Failed to create all ${missionErrors.length} mission(s). Check the backend logs and try again.`);
      return;
    }

    if (createdMissions.length > 0) {
      try {
        // Create executions for all missions
        const executions = [];
        for (const mission of createdMissions) {
          const execution = await createExecution(mission.id);
          if (execution?.id) {
            executions.push(execution.id);
          }
        }

        if (executions.length > 0) {
          // If parallel and multiple executions, use the batch endpoint
          if (parallel && executions.length > 1) {
            const batchResult = await runBatchExecutions(executions, true);
            if (batchResult) {
              // Redirect to the first execution for now
              router.push(`/executions/${executions[0]}`);
              return;
            }
          }
          // Sequential or single: run first, redirect to it
          router.push(`/executions/${executions[0]}`);
          return;
        }
      } catch (e) {
        // If execution launch fails, go to project page — user can retry from there
        console.warn("Execution launch failed, redirecting to project:", e);
      }
    }

    if (projectId) {
      router.push(`/projects/${projectId}`);
    } else {
      router.push("/executions");
    }
  };

  const handleOpenProject = () => {
    if (resolvedProjectId) {
      router.push(`/projects/${resolvedProjectId}`);
    } else {
      router.push("/projects");
    }
  };

  const showSplitBrowser = state.url && !["idle", "failed", "cancelled", "mission_created", "mission_selected"].includes(state.state);

  const showScreenshotOverlay = SCREENSHOT_STATES.has(state.state) && state.screenshots.length > 0;
  const latestScreenshot = state.screenshots.length > 0 ? state.screenshots[state.screenshots.length - 1].url : null;

  const hostname = (() => {
    try {
      return new URL(state.url).hostname;
    } catch {
      return state.url || "product";
    }
  })();

  const cleanProjectName = extractProjectName(state.url || initialUrl || hostname);

  return (
    <AgentShell
      url={state.url}
      state={state.state}
      projectName={cleanProjectName}
      onStop={handleStop}
      onBack={handleBack}
    >
      {/* ── STATE: IDLE ────────────────────────────────────────────── */}
      {state.state === "idle" && (
        <div className="flex flex-1 flex-col items-center justify-center px-6 py-16">
          <div className="w-full max-w-xl mb-8 text-center animate-in fade-in duration-300">
            <Logo size="lg" className="mb-6 justify-center" />
            <h1 className="text-h1 text-foreground mb-3 font-semibold">
              Let Kova explore your product.
            </h1>
            <p className="text-body-lg text-muted-foreground">
              Give it a website. Kova takes it from there.
            </p>
          </div>
          <div className="w-full max-w-xl">
            <KovaInput onSubmit={handleSubmit} size="lg" autoFocus />
          </div>
        </div>
      )}

      {/* ── STATE: FAILED ──────────────────────────────────────────── */}
      {state.state === "failed" && (
        <div className="flex flex-1 flex-col items-center justify-center px-6 py-16 animate-in fade-in duration-300">
          <div className="w-full max-w-md text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-destructive/10 border border-destructive/20">
              <MaterialIcon name="error" size={28} className="text-destructive" />
            </div>
            <h2 className="text-h3 text-foreground font-semibold mb-2">
              Kova couldn&apos;t reach this website.
            </h2>
            <p className="text-body-sm text-muted-foreground mb-6 leading-relaxed">
              {state.error || "Check the URL and try again."}
            </p>
            <div className="flex items-center justify-center gap-3">
              <Button variant="outline" onClick={handleBack}>
                Change URL
              </Button>
              <Button
                onClick={() => {
                  if (state.url) {
                    abortRef.current?.abort();
                    const controller = new AbortController();
                    abortRef.current = controller;
                    startedUrlRef.current = state.url;
                    startExploration(state.url, state.intent, (ev) => handleEventRef.current(ev), controller.signal).catch((err) => {
                      if (err?.name !== "AbortError") {
                        console.error("Exploration retry error:", err);
                      }
                    });
                  }
                }}
              >
                Try again
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── STATE: CANCELLED ────────────────────────────────────────── */}
      {state.state === "cancelled" && (
        <div className="flex flex-1 flex-col items-center justify-center px-6 py-16 animate-in fade-in duration-300">
          <div className="w-full max-w-md text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-secondary border border-border">
              <MaterialIcon name="stop" size={28} className="text-muted-foreground" />
            </div>
            <h2 className="text-h3 text-foreground font-semibold mb-2">
              Exploration stopped.
            </h2>
            <p className="text-body-sm text-muted-foreground mb-6">
              Kova stopped exploring this product session.
            </p>
            <Button onClick={handleBack}>
              <MaterialIcon name="arrow_back" size={16} />
              Start over
            </Button>
          </div>
        </div>
      )}

      {/* ── STATES: EXPLORING & DISCOVERING (SPLIT VIEWPORT) ─────────── */}
      {showSplitBrowser && (
        <div className="flex flex-1 flex-col lg:flex-row gap-0 overflow-hidden">
          <div className="flex-1 p-4 lg:p-6 overflow-auto">
            <AgentBrowserViewport
              url={state.url}
              state={state.state}
              currentPath={state.currentPath ?? undefined}
              latestScreenshot={latestScreenshot}
              screenshots={state.screenshots}
              showScreenshotOverlay={showScreenshotOverlay}
              isActive={state.state !== "connecting"}
              credentialRequest={state.credentialRequest}
              authMode={state.authMode}
              onCredentialSubmit={handleCredentialSubmit}
              onAuthChoice={handleAuthChoice}
              credentialError={credentialError}
              credentialLoading={credentialLoading}
              onUrlChange={handleUrlChange}
              onThumbnailClick={handleThumbnailClick}
              className="h-full"
            />
          </div>

          <aside className="w-full lg:w-84 border-t lg:border-t-0 lg:border-l border-border bg-card/50 p-4 lg:p-5 overflow-auto flex flex-col justify-between">
            <div>
              <AgentStatus state={state.state} url={state.url} className="mb-6" />
              <AgentActivity activities={state.activities} />
            </div>

            <div className="pt-4 border-t border-border/60 mt-4 text-center">
              <p className="text-[11px] text-muted-foreground/60 font-mono">
                Isolated sandbox • No local secrets retained
              </p>
            </div>
          </aside>
        </div>
      )}

      {/* ── STATE: ASKING ──────────────────────────────────────────── */}
      {state.state === "asking" && state.question && (
        <div className="flex flex-1 flex-col items-center justify-center px-6 py-16 animate-in fade-in duration-300">
          <AgentQuestion
            title={state.question.title}
            description={state.question.description}
            options={state.question.options}
            onSelectOption={handleAnswerQuestion}
            submitLabel="Continue exploration"
          />
        </div>
      )}

      {/* ── STATE: READY (SUGGESTED MISSIONS FULL-PAGE DIALOG) ───────── */}
      {state.state === "ready" && state.missions.length > 0 && showMissionsDialog && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Discovered Journeys"
          className="fixed inset-0 z-40 bg-background/95 backdrop-blur-md overflow-y-auto flex flex-col justify-start items-center p-4 sm:p-6 md:p-10 animate-in fade-in zoom-in-95 duration-200"
        >
          <div className="w-full max-w-2xl relative pt-4 pb-12">
            <div className="flex justify-end mb-2">
              <button
                type="button"
                onClick={() => setShowMissionsDialog(false)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-caption text-muted-foreground hover:text-foreground hover:bg-secondary border border-border/60 transition-colors"
                title="View browser underneath"
              >
                <MaterialIcon name="visibility" size={16} />
                <span>View browser</span>
              </button>
            </div>

            <MissionSuggestions
              missions={state.missions}
              recommendation={state.recommendationNote}
              projectName={cleanProjectName}
              onRun={handleRunMissions}
              onOpenProject={handleOpenProject}
              onUpdateMission={updateMission}
            />
          </div>
        </div>
      )}

      {/* Floating button to reopen missions dialog when peeking browser */}
      {state.state === "ready" && state.missions.length > 0 && !showMissionsDialog && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 animate-in fade-in slide-in-from-bottom-4 duration-300">
          <Button
            onClick={() => setShowMissionsDialog(true)}
            size="lg"
            className="shadow-xl font-medium px-6 py-3 rounded-full flex items-center gap-2 bg-primary text-primary-foreground hover:bg-primary/90"
          >
            <MaterialIcon name="auto_awesome" size={20} />
            <span>Review {state.missions.length} Journeys</span>
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse ml-1" />
          </Button>
        </div>
      )}

      {/* ── STATE: READY (ZERO STATE) ─────────────────────────────────── */}
      {state.state === "ready" && state.missions.length === 0 && (
        <div className="flex flex-1 flex-col items-center justify-center px-6 py-16 animate-in fade-in duration-300">
          <div className="text-center max-w-md">
            <MaterialIcon
              name="search_off"
              size={48}
              className="mx-auto mb-4 text-muted-foreground"
            />
            <h2 className="text-h3 font-semibold text-foreground mb-2">
              No journeys discovered
            </h2>
            <p className="text-body-sm text-muted-foreground mb-6">
              Kova explored {state.url || "the target page"} but could not find enough interactive elements to form automated missions.
            </p>
            <div className="flex items-center justify-center gap-3">
              <Button variant="outline" onClick={handleBack}>
                Try another URL
              </Button>
              <Button onClick={handleOpenProject}>
                View Project
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── STATE: MISSION CREATED (TRANSITION TO EXECUTION) ──────────── */}
      {(state.state === "mission_created" || state.state === "mission_selected") && (
        <div className="flex flex-1 flex-col items-center justify-center px-6 py-16 animate-in fade-in duration-300">
          <div className="text-center">
            <MaterialIcon
              name="progress_activity"
              size={36}
              className="mx-auto mb-4 text-primary animate-spin"
            />
            <h2 className="text-h3 font-semibold text-foreground mb-2">
              Preparing mission execution.
            </h2>
            <p className="text-body-sm text-muted-foreground">
              Kova is launching the isolated browser container and taking over.
            </p>
          </div>
        </div>
      )}

      {/* ── SCREENSHOT GALLERY DIALOG ──────────────────────────────── */}
      <ScreenshotGallery
        screenshots={state.screenshots}
        initialIndex={galleryIndex}
        open={galleryOpen}
        onClose={() => setGalleryOpen(false)}
      />
    </AgentShell>
  );
}
