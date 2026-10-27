"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { cn } from "@/lib/utils";
import { MaterialIcon } from "@/components/shared/material-icon";
import { getApiBaseUrl, getBrowserSessionToken } from "@/lib/api/client";

type ViewportState =
  | "connecting"
  | "observing"
  | "navigating"
  | "executing"
  | "verifying"
  | "paused"
  | "user_control"
  | "resuming"
  | "failed"
  | "disconnected";

interface ViewportMessage {
  type: "frame" | "state" | "control_changed" | "takeover_request" | "pong";
  state?: string;
  url?: string;
  title?: string;
  control?: string;
  cursor?: { x: number; y: number };
  loading?: boolean;
}

interface LiveViewportProps {
  executionId: string;
  className?: string;
  fallbackScreenshot?: string | null;
  onTakeover?: () => void;
  onRelease?: () => void;
  hideHeader?: boolean;
}

const stateConfig: Record<ViewportState, { label: string; color: string; icon: string }> = {
  connecting: { label: "Connecting...", color: "bg-muted-foreground/50", icon: "sync" },
  observing: { label: "Observing", color: "bg-primary", icon: "visibility" },
  navigating: { label: "Navigating", color: "bg-blue-500", icon: "open_in_new" },
  executing: { label: "Executing", color: "bg-primary", icon: "play_arrow" },
  verifying: { label: "Verifying", color: "bg-emerald-500", icon: "check_circle" },
  paused: { label: "Paused", color: "bg-amber-500", icon: "pause_circle" },
  user_control: { label: "You have control", color: "bg-amber-500", icon: "person" },
  resuming: { label: "Resuming", color: "bg-primary", icon: "play_circle" },
  failed: { label: "Failed", color: "bg-destructive", icon: "error" },
  disconnected: { label: "Disconnected", color: "bg-muted-foreground/30", icon: "wifi_off" },
};

const RECONNECT_DELAY_MS = 2000;
const MAX_RECONNECT_ATTEMPTS = 10;
const BROWSER_VIEWPORT = { width: 1280, height: 720 };

function getCanvasRelativeCoords(
  e: React.MouseEvent<HTMLCanvasElement>,
  canvas: HTMLCanvasElement
): { x: number; y: number } {
  const rect = canvas.getBoundingClientRect();
  const scaleX = BROWSER_VIEWPORT.width / rect.width;
  const scaleY = BROWSER_VIEWPORT.height / rect.height;
  return {
    x: Math.round((e.clientX - rect.left) * scaleX),
    y: Math.round((e.clientY - rect.top) * scaleY),
  };
}

function toWsUrl(path: string, param: string, paramName: "ticket" | "token" = "ticket"): string {
  const base = getApiBaseUrl();
  const httpUrl = base.startsWith("http") ? base : `http://${base}`;
  const u = new URL(httpUrl);
  const protocol = u.protocol === "https:" ? "wss:" : "ws:";
  const qs = param ? `?${paramName}=${encodeURIComponent(param)}` : "";
  return `${protocol}//${u.host}${path}${qs}`;
}

export function LiveViewport({
  executionId,
  className,
  fallbackScreenshot,
  onTakeover,
  onRelease,
  hideHeader = false,
}: LiveViewportProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const framePendingRef = useRef(false);
  const leaseIdRef = useRef<string | null>(null);
  const generationRef = useRef<number>(1);
  const [hasReceivedFrame, setHasReceivedFrame] = useState(false);
  const [state, setState] = useState<ViewportState>("connecting");
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [showTakeoverDialog, setShowTakeoverDialog] = useState(false);
  const [controlState, setControlState] = useState<"agent" | "human">("agent");
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const [checkpoint, setCheckpoint] = useState<{ type: string; description: string; details?: any } | null>(null);
  const [takeoverError, setTakeoverError] = useState<string | null>(null);

  const isHumanControlled = controlState === "human" || state === "user_control";

  const sendInput = useCallback((msg: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: "input",
          lease_id: leaseIdRef.current,
          generation: generationRef.current,
          ...msg,
        })
      );
    }
  }, []);

  const sendNav = useCallback((kind: "back" | "forward" | "reload") => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: "nav",
          kind,
          lease_id: leaseIdRef.current,
          generation: generationRef.current,
        })
      );
    }
  }, []);


  const connect = useCallback(async () => {
    if (!executionId) return;

    let wsUrl: string;
    const token = (await getBrowserSessionToken()) ?? "";
    try {
      const res = await fetch(`${getApiBaseUrl()}/viewport/ticket`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const data = await res.json();
        wsUrl = toWsUrl(`/ws/viewport/${executionId}`, data.ticket, "ticket");
      } else {
        wsUrl = toWsUrl(`/ws/viewport/${executionId}`, token, "token");
      }
    } catch {
      wsUrl = toWsUrl(`/ws/viewport/${executionId}`, token, "token");
    }

    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl);
    } catch {
      setState("disconnected");
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectAttemptsRef.current = 0;
      setState((s) => (s === "disconnected" ? "disconnected" : "observing"));
    };

    ws.onmessage = (event) => {
      if (event.data instanceof Blob) {
        // Latest-wins: drop frame if previous still decoding
        if (framePendingRef.current) return;
        framePendingRef.current = true;
        const objectUrl = URL.createObjectURL(event.data);
        const img = new Image();
        img.onload = () => {
          const canvas = canvasRef.current;
          if (canvas) {
            // Canonical browser viewport is fixed 1280×720
            if (canvas.width !== BROWSER_VIEWPORT.width) {
              canvas.width = BROWSER_VIEWPORT.width;
              canvas.height = BROWSER_VIEWPORT.height;
            }
            const ctx = canvas.getContext("2d");
            if (ctx) {
              ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
              setHasReceivedFrame(true);
            }
          }
          URL.revokeObjectURL(objectUrl);
          framePendingRef.current = false;
        };
        img.onerror = () => {
          URL.revokeObjectURL(objectUrl);
          framePendingRef.current = false;
        };
        img.src = objectUrl;
      } else {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "takeover_granted") {
            leaseIdRef.current = msg.lease_id || null;
            if (msg.generation) generationRef.current = msg.generation;
            setControlState("human");
            setState("user_control");
            setTakeoverError(null);
            onTakeover?.();
          } else if (msg.type === "takeover_rejected") {
            setTakeoverError(msg.reason || "Browser takeover unavailable");
            setTimeout(() => setTakeoverError(null), 4000);
          } else if (msg.type === "control_changed") {
            if (msg.lease_id) leaseIdRef.current = msg.lease_id;
            if (msg.generation) generationRef.current = msg.generation;
            if (msg.checkpoint !== undefined) setCheckpoint(msg.checkpoint);
            if (msg.control === "human") {
              setControlState("human");
              setState("user_control");
            } else if (msg.control === "paused") {
              setState("paused");
            } else if (msg.control === "agent") {
              setControlState("agent");
              leaseIdRef.current = null;
              setState("resuming");
              setTimeout(() => setState("executing"), 1500);
            }
          } else if (msg.type === "state") {
            if (msg.checkpoint !== undefined) setCheckpoint(msg.checkpoint);
            if (msg.state) setState(msg.state as ViewportState);
            if (msg.url) setUrl(msg.url);
            if (msg.title) setTitle(msg.title);
            if (msg.control === "human" || msg.control === "agent") {
              setControlState(msg.control);
            }
            if (msg.cursor) setCursor(msg.cursor);
            else if (msg.state !== "paused" && msg.state !== "user_control") setCursor(null);
          } else if (msg.type === "frame") {
            if (msg.state && controlState !== "human" && state !== "paused" && state !== "user_control") {
              setState(msg.state as ViewportState);
            }
          } else if (msg.type === "takeover_request") {
            setShowTakeoverDialog(true);
          }
        } catch {
          // Ignore parse errors
        }
      }
    };


    ws.onclose = () => {
      if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
        setState("connecting");
        reconnectTimerRef.current = setTimeout(() => {
          reconnectAttemptsRef.current += 1;
          connect();
        }, RECONNECT_DELAY_MS * Math.min(reconnectAttemptsRef.current + 1, 5));
      } else {
        setState("disconnected");
      }
    };

    ws.onerror = () => {};
  }, [executionId]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  // Keepalive ping
  useEffect(() => {
    const id = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "ping" }));
      }
    }, 25000);
    return () => clearInterval(id);
  }, []);

  const handleTakeoverAccept = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: "takeover_accept" }));
    setShowTakeoverDialog(false);
  }, []);

  const handleTakeoverReject = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: "takeover_reject" }));
    setShowTakeoverDialog(false);
    onRelease?.();
  }, [onRelease]);

  const handleReturnControl = useCallback(() => {
    wsRef.current?.send(
      JSON.stringify({
        type: "return_control",
        lease_id: leaseIdRef.current,
      })
    );
    leaseIdRef.current = null;
    setState("resuming");
    setControlState("agent");
    onRelease?.();
  }, [onRelease]);

  const handlePause = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: "pause" }));
    setState("paused");
  }, []);

  const handleResume = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: "resume" }));
    setState("resuming");
  }, []);


  // Mouse input handlers
  const handleCanvasMouseDown = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isHumanControlled) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.focus();
    const { x, y } = getCanvasRelativeCoords(e, canvas);
    sendInput({ kind: "mouse_down", x, y, button: e.button });
  }, [isHumanControlled, sendInput]);

  const handleCanvasMouseUp = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isHumanControlled) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const { x, y } = getCanvasRelativeCoords(e, canvas);
    sendInput({ kind: "mouse_up", x, y, button: e.button });
  }, [isHumanControlled, sendInput]);

  const handleCanvasClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    // When agent controls: click opens takeover affordance, does not inject input
    if (!isHumanControlled) {
      if (state !== "failed" && state !== "disconnected") {
        setShowTakeoverDialog(true);
      }
      return;
    }
    const canvas = canvasRef.current;
    if (!canvas) return;
    const { x, y } = getCanvasRelativeCoords(e, canvas);
    sendInput({ kind: "click", x, y });
  }, [isHumanControlled, state, sendInput]);

  const handleCanvasMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isHumanControlled) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const { x, y } = getCanvasRelativeCoords(e, canvas);
    sendInput({ kind: "mouse_move", x, y });
  }, [isHumanControlled, sendInput]);

  // Non-passive wheel event listener on the canvas DOM element to allow preventDefault
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleWheel = (e: WheelEvent) => {
      if (!isHumanControlled) return;
      e.preventDefault();
      sendInput({ kind: "scroll", delta_x: e.deltaX, delta_y: e.deltaY });
    };

    canvas.addEventListener("wheel", handleWheel, { passive: false });
    return () => {
      canvas.removeEventListener("wheel", handleWheel);
    };
  }, [isHumanControlled, sendInput]);

  // Keyboard input handler
  useEffect(() => {
    if (!isHumanControlled) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        (e.target as HTMLElement)?.isContentEditable
      ) {
        return;
      }
      if (e.key.startsWith("F") && e.key.length <= 3) return;
      if (e.ctrlKey && e.shiftKey) return;
      if (e.metaKey && e.shiftKey) return;

      e.preventDefault();
      sendInput({ kind: "key_down", key: e.key });
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        (e.target as HTMLElement)?.isContentEditable
      ) {
        return;
      }
      if (e.key.startsWith("F") && e.key.length <= 3) return;
      if (e.ctrlKey && e.shiftKey) return;
      if (e.metaKey && e.shiftKey) return;

      e.preventDefault();
      sendInput({ kind: "key_up", key: e.key });
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, [isHumanControlled, sendInput]);

  const config = stateConfig[state];
  const cursorPct = cursor
    ? {
        left: `${(cursor.x / BROWSER_VIEWPORT.width) * 100}%`,
        top: `${(cursor.y / BROWSER_VIEWPORT.height) * 100}%`,
      }
    : null;

  return (
    <div className={cn("relative rounded-lg overflow-hidden border border-border bg-black", className)}>
      {/* Browser toolbar (hidden when embedded in an existing browser frame) */}
      {!hideHeader && (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-background/95 border-b border-border">
          <div className={cn("h-2 w-2 rounded-full", config.color, state === "observing" || state === "executing" ? "animate-pulse" : "")} />
          <MaterialIcon name={config.icon} className="h-3.5 w-3.5 text-muted-foreground" />
          <div className="flex items-center gap-1">
            <button
              type="button"
              aria-label="Back"
              title={isHumanControlled ? "Back" : "Take over control to navigate"}
              disabled={!isHumanControlled}
              onClick={() => sendNav("back")}
              className={cn(
                "p-1 rounded text-muted-foreground transition-colors",
                isHumanControlled ? "hover:bg-muted hover:text-foreground cursor-pointer" : "opacity-40 cursor-not-allowed"
              )}
            >
              <MaterialIcon name="arrow_back" size={14} />
            </button>
            <button
              type="button"
              aria-label="Forward"
              title={isHumanControlled ? "Forward" : "Take over control to navigate"}
              disabled={!isHumanControlled}
              onClick={() => sendNav("forward")}
              className={cn(
                "p-1 rounded text-muted-foreground transition-colors",
                isHumanControlled ? "hover:bg-muted hover:text-foreground cursor-pointer" : "opacity-40 cursor-not-allowed"
              )}
            >
              <MaterialIcon name="arrow_forward" size={14} />
            </button>
            <button
              type="button"
              aria-label="Reload"
              title={isHumanControlled ? "Reload" : "Take over control to reload"}
              disabled={!isHumanControlled}
              onClick={() => sendNav("reload")}
              className={cn(
                "p-1 rounded text-muted-foreground transition-colors",
                isHumanControlled ? "hover:bg-muted hover:text-foreground cursor-pointer" : "opacity-40 cursor-not-allowed"
              )}
            >
              <MaterialIcon name="refresh" size={14} />
            </button>
          </div>
          <span className="text-caption text-muted-foreground truncate flex-1">{url || "No URL"}</span>
          {title && <span className="text-caption text-muted-foreground/60 truncate max-w-[200px]">{title}</span>}
        </div>
      )}

      {/* Viewport canvas */}
      <div className="relative aspect-video bg-neutral-950 flex items-center justify-center overflow-hidden">
        {!hasReceivedFrame && !fallbackScreenshot && (
          <div className="absolute inset-0 flex flex-col items-center justify-center p-6 text-center z-0 bg-neutral-950">
            <div className="relative mb-3 flex h-14 w-14 items-center justify-center rounded-2xl border border-primary/30 bg-primary/10 shadow-lg">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-2xl bg-primary opacity-20" />
              <MaterialIcon name="smart_toy" size={28} className="text-primary animate-pulse" />
            </div>
            <p className="text-body-sm font-medium text-neutral-200">
              Initializing Kova Playwright browser...
            </p>
            <p className="text-caption text-neutral-400 mt-0.5 max-w-xs">
              Live viewport frames and interactions will stream here in real time.
            </p>
          </div>
        )}
        {fallbackScreenshot && !hasReceivedFrame && (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={fallbackScreenshot}
            alt="Browser preview"
            className="absolute inset-0 w-full h-full object-contain pointer-events-none select-none opacity-80"
          />
        )}
        <canvas
          ref={canvasRef}
          width={BROWSER_VIEWPORT.width}
          height={BROWSER_VIEWPORT.height}
          tabIndex={isHumanControlled ? 0 : -1}
          className={cn(
            "w-full h-full object-contain outline-none relative z-10",
            isHumanControlled ? "cursor-pointer focus:ring-1 focus:ring-primary/30" : "cursor-default",
            !hasReceivedFrame && fallbackScreenshot && "opacity-0"
          )}
          style={{ imageRendering: "auto" }}
          onMouseDown={handleCanvasMouseDown}
          onMouseUp={handleCanvasMouseUp}
          onClick={handleCanvasClick}
          onMouseMove={isHumanControlled ? handleCanvasMouseMove : undefined}
        />

        {/* Agent cursor overlay */}
        {cursorPct && !isHumanControlled && (
          <div
            className="absolute pointer-events-none z-20"
            style={{ left: cursorPct.left, top: cursorPct.top, transform: "translate(-2px, -2px)" }}
          >
            <svg width="18" height="24" viewBox="0 0 18 24" fill="none" aria-hidden>
              <path d="M1 1L1 18L6 13L10 22L13 20L9 11L16 11L1 1Z" fill="white" stroke="black" strokeWidth="1.5" />
            </svg>
          </div>
        )}

        {/* State overlay */}
        <div className="absolute top-2 left-2 flex items-center gap-1.5 px-2 py-1 rounded bg-background/80 backdrop-blur-sm border border-border/50">
          <div className={cn("h-1.5 w-1.5 rounded-full", config.color, "animate-pulse")} />
          <span className="text-caption font-medium">{config.label}</span>
        </div>

        {/* Agent control glow */}
        {(state === "executing" || state === "navigating") && !isHumanControlled && (
          <div className="absolute inset-0 pointer-events-none border-2 border-primary/30 rounded-lg animate-pulse" />
        )}

        {/* User control indicator */}
        {isHumanControlled && (
          <div className="absolute inset-0 pointer-events-none border-2 border-amber-500/50 rounded-lg" />
        )}

        {/* Checkpoint banner */}
        {checkpoint && (
          <div className="absolute top-10 left-3 right-3 z-30 flex items-center justify-between gap-3 p-3 rounded-lg bg-amber-950/90 border border-amber-500/50 text-amber-200 backdrop-blur-md shadow-xl animate-in fade-in slide-in-from-top-2 duration-200">
            <div className="flex items-center gap-2.5 min-w-0">
              <MaterialIcon name="security" className="w-5 h-5 text-amber-400 shrink-0" />
              <div className="text-xs">
                <p className="font-semibold text-amber-100">Verification Barrier Encountered</p>
                <p className="text-amber-200/80 truncate">{checkpoint.description || "Human intervention required"}</p>
              </div>
            </div>
            {!isHumanControlled ? (
              <button
                type="button"
                onClick={handleTakeoverAccept}
                className="px-3 py-1 bg-amber-500 hover:bg-amber-600 text-neutral-950 font-medium text-xs rounded-md shrink-0 transition-colors cursor-pointer"
              >
                Solve in Browser
              </button>
            ) : (
              <span className="text-[11px] font-mono text-amber-300/80 px-2 py-0.5 rounded border border-amber-400/30">
                Solving Challenge...
              </span>
            )}
          </div>
        )}

        {/* Takeover error notification */}
        {takeoverError && (
          <div className="absolute top-10 left-3 right-3 z-30 p-2.5 rounded-lg bg-destructive/90 border border-destructive text-destructive-foreground text-xs shadow-lg animate-in fade-in duration-200">
            {takeoverError}
          </div>
        )}

        {/* Takeover dialog */}
        {showTakeoverDialog && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/80 backdrop-blur-sm z-40">
            <div className="bg-background border border-border rounded-lg p-4 shadow-lg max-w-sm">
              <h3 className="text-sm font-medium mb-2">Take control?</h3>
              <p className="text-caption text-muted-foreground mb-4">
                Kova is currently controlling this browser. Take over to interact manually?
              </p>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={handleTakeoverReject}
                  className="px-3 py-1.5 text-caption text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                >
                  Keep observing
                </button>
                <button
                  onClick={handleTakeoverAccept}
                  className="px-3 py-1.5 text-caption bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors cursor-pointer"
                >
                  Take control
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Control status bar — always visible */}
      <div className="flex items-center justify-between gap-2 px-3 py-2 bg-background/95 border-t border-border">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={cn(
              "h-2 w-2 rounded-full shrink-0",
              state === "failed"
                ? "bg-destructive"
                : state === "disconnected"
                ? "bg-muted-foreground/40"
                : isHumanControlled
                ? "bg-amber-500"
                : state === "paused"
                ? "bg-amber-400"
                : "bg-primary animate-pulse"
            )}
          />
          <span className="text-caption text-muted-foreground truncate">
            {state === "failed"
              ? "Execution ended"
              : state === "disconnected"
              ? "Session ended"
              : isHumanControlled
              ? "You are controlling"
              : state === "paused"
              ? "Execution paused"
              : "Kova is controlling"}
          </span>
        </div>
        {state === "failed" || state === "disconnected" ? (
          <span className="text-caption text-muted-foreground/50 text-[11px] font-mono px-2 py-0.5 rounded border border-border/40">
            Inactive
          </span>
        ) : isHumanControlled ? (
          <button
            type="button"
            onClick={handleReturnControl}
            className="flex items-center gap-1 rounded-md bg-amber-500 text-white px-2.5 py-1 text-caption font-medium hover:bg-amber-600 transition-colors shrink-0 cursor-pointer"
          >
            <MaterialIcon name="undo" size={14} />
            <span>Return control to Kova</span>
          </button>
        ) : (
          <div className="flex items-center gap-1.5">
            {state === "paused" ? (
              <button
                type="button"
                onClick={handleResume}
                className="flex items-center gap-1 rounded-md bg-primary text-primary-foreground px-2 py-1 text-caption font-medium hover:bg-primary/90 transition-colors shrink-0 cursor-pointer"
              >
                <MaterialIcon name="play_arrow" size={14} />
                <span>Resume</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={handlePause}
                className="flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-caption font-medium text-muted-foreground hover:text-foreground transition-colors shrink-0 cursor-pointer"
              >
                <MaterialIcon name="pause" size={14} />
                <span>Pause</span>
              </button>
            )}
            <button
              type="button"
              onClick={handleTakeoverAccept}
              className="flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-caption font-medium text-foreground hover:bg-muted transition-colors shrink-0 cursor-pointer"
            >
              <MaterialIcon name="person" size={14} />
              <span>Take over</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

