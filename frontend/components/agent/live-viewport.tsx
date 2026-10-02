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
  onTakeover?: () => void;
  onRelease?: () => void;
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

function toWsUrl(path: string, token: string): string {
  const base = getApiBaseUrl();
  const httpUrl = base.startsWith("http") ? base : `http://${base}`;
  const u = new URL(httpUrl);
  const protocol = u.protocol === "https:" ? "wss:" : "ws:";
  const qs = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${protocol}//${u.host}${path}${qs}`;
}

export function LiveViewport({
  executionId,
  className,
  onTakeover,
  onRelease,
}: LiveViewportProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const framePendingRef = useRef(false);
  const [state, setState] = useState<ViewportState>("connecting");
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [showTakeoverDialog, setShowTakeoverDialog] = useState(false);
  const [controlState, setControlState] = useState<"agent" | "human">("agent");
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);

  const isHumanControlled = controlState === "human" || state === "user_control";

  const sendInput = useCallback((msg: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "input", ...msg }));
    }
  }, []);

  const sendNav = useCallback((kind: "back" | "forward" | "reload") => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "nav", kind }));
    }
  }, []);

  const connect = useCallback(async () => {
    if (!executionId) return;

    const token = (await getBrowserSessionToken()) ?? "";
    const wsUrl = toWsUrl(`/ws/viewport/${executionId}`, token);

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
          const msg: ViewportMessage = JSON.parse(event.data);
          if (msg.type === "state" && msg.state) {
            setState(msg.state as ViewportState);
            if (msg.url) setUrl(msg.url);
            if (msg.title) setTitle(msg.title);
            if (msg.control === "human" || msg.control === "agent") {
              setControlState(msg.control);
            }
            if (msg.cursor) setCursor(msg.cursor);
            else if (msg.state !== "paused" && msg.state !== "user_control") setCursor(null);
          } else if (msg.type === "control_changed" && msg.control) {
            setControlState(msg.control as "agent" | "human");
            if (msg.control === "agent") {
              setState("resuming");
              setTimeout(() => setState("executing"), 1500);
            } else {
              setState("user_control");
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
    setState("user_control");
    setControlState("human");
    onTakeover?.();
  }, [onTakeover]);

  const handleTakeoverReject = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: "takeover_reject" }));
    setShowTakeoverDialog(false);
    onRelease?.();
  }, [onRelease]);

  const handleReturnControl = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: "return_control" }));
    setState("resuming");
    setControlState("agent");
    onRelease?.();
  }, [onRelease]);

  // Mouse input handlers
  const handleCanvasMouseDown = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isHumanControlled) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
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
      setShowTakeoverDialog(true);
      return;
    }
    const canvas = canvasRef.current;
    if (!canvas) return;
    const { x, y } = getCanvasRelativeCoords(e, canvas);
    sendInput({ kind: "click", x, y });
  }, [isHumanControlled, sendInput]);

  const handleCanvasMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isHumanControlled) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const { x, y } = getCanvasRelativeCoords(e, canvas);
    sendInput({ kind: "mouse_move", x, y });
  }, [isHumanControlled, sendInput]);

  const handleCanvasWheel = useCallback((e: React.WheelEvent<HTMLCanvasElement>) => {
    if (!isHumanControlled) return;
    e.preventDefault();
    sendInput({ kind: "scroll", delta_x: e.deltaX, delta_y: e.deltaY });
  }, [isHumanControlled, sendInput]);

  // Keyboard input handler
  useEffect(() => {
    if (!isHumanControlled) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      e.preventDefault();
      sendInput({ kind: "key_down", key: e.key });
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
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
      {/* Browser toolbar */}
      <div className="flex items-center gap-2 px-3 py-1.5 bg-background/95 border-b border-border">
        <div className={cn("h-2 w-2 rounded-full", config.color, state === "observing" || state === "executing" ? "animate-pulse" : "")} />
        <MaterialIcon name={config.icon} className="h-3.5 w-3.5 text-muted-foreground" />
        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-label="Back"
            title="Back"
            onClick={() => sendNav("back")}
            className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
          >
            <MaterialIcon name="arrow_back" size={14} />
          </button>
          <button
            type="button"
            aria-label="Forward"
            title="Forward"
            onClick={() => sendNav("forward")}
            className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
          >
            <MaterialIcon name="arrow_forward" size={14} />
          </button>
          <button
            type="button"
            aria-label="Reload"
            title="Reload"
            onClick={() => sendNav("reload")}
            className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
          >
            <MaterialIcon name="refresh" size={14} />
          </button>
        </div>
        <span className="text-caption text-muted-foreground truncate flex-1">{url || "No URL"}</span>
        {title && <span className="text-caption text-muted-foreground/60 truncate max-w-[200px]">{title}</span>}
      </div>

      {/* Viewport canvas */}
      <div className="relative aspect-video bg-black">
        <canvas
          ref={canvasRef}
          width={BROWSER_VIEWPORT.width}
          height={BROWSER_VIEWPORT.height}
          className={cn(
            "w-full h-full object-contain",
            isHumanControlled ? "cursor-pointer" : "cursor-default"
          )}
          style={{ imageRendering: "auto" }}
          onMouseDown={handleCanvasMouseDown}
          onMouseUp={handleCanvasMouseUp}
          onClick={handleCanvasClick}
          onMouseMove={isHumanControlled ? handleCanvasMouseMove : undefined}
          onWheel={isHumanControlled ? handleCanvasWheel : undefined}
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
                  className="px-3 py-1.5 text-caption text-muted-foreground hover:text-foreground transition-colors"
                >
                  Keep observing
                </button>
                <button
                  onClick={handleTakeoverAccept}
                  className="px-3 py-1.5 text-caption bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors"
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
              isHumanControlled ? "bg-amber-500" : "bg-primary animate-pulse"
            )}
          />
          <span className="text-caption text-muted-foreground truncate">
            {isHumanControlled ? "You are controlling" : "Kova is controlling"}
          </span>
        </div>
        {isHumanControlled ? (
          <button
            type="button"
            onClick={handleReturnControl}
            className="flex items-center gap-1 rounded-md bg-amber-500 text-white px-2.5 py-1 text-caption font-medium hover:bg-amber-600 transition-colors shrink-0"
          >
            <MaterialIcon name="undo" size={14} />
            <span>Return control to Kova</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={handleTakeoverAccept}
            className="flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-caption font-medium text-foreground hover:bg-muted transition-colors shrink-0"
          >
            <MaterialIcon name="person" size={14} />
            <span>Take over</span>
          </button>
        )}
      </div>
    </div>
  );
}
