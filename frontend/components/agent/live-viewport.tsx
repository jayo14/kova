"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { cn } from "@/lib/utils";
import { MaterialIcon } from "@/components/shared/material-icon";
import { getApiBaseUrl, getBrowserSessionToken } from "@/lib/api/client";
import {
  applyServerMessage,
  frameAgeMs,
  initialViewportTruth,
  isConfirmedHuman,
  isFrameStale,
  isPendingHandoff,
  markFrameAcked,
  markReturnRequested,
  markTakeoverDeclined,
  markTakeoverRequested,
  maskingCopy,
  resetViewportTruth,
} from "@/lib/viewport/truth";
import type { ServerMessage, ViewportTruth } from "@/lib/viewport/truth";

type ViewportState =
  | "connecting"
  | "loading"
  | "observing"
  | "navigating"
  | "executing"
  | "verifying"
  | "validating_page"
  | "discovering"
  | "analyzing"
  | "planning"
  | "ready"
  | "completed"
  | "paused"
  | "user_control"
  | "resuming"
  | "failed"
  | "disconnected"
  | string;

export type ConnectionHop =
  | "worker_started"
  | "browser_launched"
  | "stream_connected"
  | "first_frame_delivered";

interface ViewportMessage extends ServerMessage {
  type:
    | "frame"
    | "state"
    | "control_changed"
    | "takeover_request"
    | "takeover_granted"
    | "takeover_rejected"
    | "masking_status"
    | "connection_quality"
    | "control_error"
    | "interaction_rejected"
    | "pause_requested"
    | "resume_requested"
    | "lease_expired"
    | "connection_hop"
    | "load_phase"
    | "pending_request"
    | "platform_wake"
    | "progress"
    | "pong";
  url?: string;
  title?: string;
  cursor?: { x: number; y: number };
  loading?: boolean;
  checkpoint?: { type: string; description: string; details?: unknown };
  hop?: ConnectionHop;
  phase?: string;
  host?: string;
  age_s?: number;
  message?: string;
  id?: string;
}

interface LiveViewportProps {
  executionId: string;
  className?: string;
  fallbackScreenshot?: string | null;
  onTakeover?: () => void;
  onRelease?: () => void;
  onRetry?: () => void;
  hideHeader?: boolean;
  connectionHop?: ConnectionHop | null;
  loadPhase?: string | null;
  pendingMessage?: string | null;
  platformWakeMessage?: string | null;
}

interface StateDisplayConfig {
  label: string;
  color: string;
  icon: string;
}

const DEFAULT_STATE_CONFIG: StateDisplayConfig = {
  label: "Observing",
  color: "bg-primary",
  icon: "visibility",
};

const stateConfig: Record<string, StateDisplayConfig> = {
  connecting: { label: "Connecting...", color: "bg-muted-foreground/50", icon: "sync" },
  loading: { label: "Loading site...", color: "bg-primary", icon: "sync" },
  observing: { label: "Observing", color: "bg-primary", icon: "visibility" },
  navigating: { label: "Navigating", color: "bg-blue-500", icon: "open_in_new" },
  executing: { label: "Executing", color: "bg-primary", icon: "play_arrow" },
  verifying: { label: "Verifying", color: "bg-emerald-500", icon: "check_circle" },
  validating_page: { label: "Validating...", color: "bg-blue-500", icon: "search" },
  discovering: { label: "Discovering...", color: "bg-primary", icon: "explore" },
  analyzing: { label: "Analyzing...", color: "bg-primary", icon: "auto_awesome" },
  planning: { label: "Planning...", color: "bg-primary", icon: "psychology" },
  ready: { label: "Ready", color: "bg-emerald-500", icon: "check_circle" },
  completed: { label: "Completed", color: "bg-emerald-500", icon: "check_circle" },
  paused: { label: "Paused", color: "bg-amber-500", icon: "pause_circle" },
  user_control: { label: "You have control", color: "bg-amber-500", icon: "person" },
  resuming: { label: "Resuming", color: "bg-primary", icon: "play_circle" },
  failed: { label: "Failed", color: "bg-destructive", icon: "error" },
  disconnected: { label: "Disconnected", color: "bg-muted-foreground/30", icon: "wifi_off" },
};

function resolveViewportStateConfig(rawState: string | undefined | null): StateDisplayConfig {
  if (!rawState) return DEFAULT_STATE_CONFIG;
  const key = String(rawState).toLowerCase().trim();
  const found = stateConfig[key];
  if (found) return found;

  return {
    label: key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, " "),
    color: "bg-primary",
    icon: "visibility",
  };
}

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

function toWsUrl(path: string): string {
  const base = getApiBaseUrl();
  const httpUrl = base.startsWith("http") ? base : `http://${base}`;
  const u = new URL(httpUrl);
  const protocol = u.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${u.host}${path}`;
}

export function LiveViewport({
  executionId,
  className,
  fallbackScreenshot,
  onTakeover,
  onRelease,
  onRetry,
  hideHeader = false,
  connectionHop: propConnectionHop = null,
  loadPhase: propLoadPhase = null,
  pendingMessage: propPendingMessage = null,
  platformWakeMessage: propPlatformWakeMessage = null,
}: LiveViewportProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const framePendingRef = useRef(false);
  const leaseIdRef = useRef<string | null>(null);
  const generationRef = useRef<number>(1);
  const [hasReceivedFrame, setHasReceivedFrame] = useState(false);
  const [serverConnectionHop, setServerConnectionHop] = useState<ConnectionHop | null>(null);
  const [serverLoadPhase, setServerLoadPhase] = useState<string | null>(null);
  const [serverPendingMessage, setServerPendingMessage] = useState<string | null>(null);
  const [serverPlatformWakeMessage, setServerPlatformWakeMessage] = useState<string | null>(null);

  const activeHop = propConnectionHop ?? serverConnectionHop;
  const activeLoadPhase = propLoadPhase ?? serverLoadPhase;
  const activePendingMessage = propPendingMessage ?? serverPendingMessage;
  const activePlatformWakeMessage = propPlatformWakeMessage ?? serverPlatformWakeMessage;

  const [state, setState] = useState<ViewportState>("connecting");
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [showTakeoverDialog, setShowTakeoverDialog] = useState(false);
  const [truth, setTruth] = useState<ViewportTruth>(initialViewportTruth);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const [checkpoint, setCheckpoint] = useState<{ type: string; description: string; details?: unknown } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const pendingFrameSeqRef = useRef<number | null>(null);
  const truthRef = useRef(truth);

  // Server-confirmed truth only: the client never upgrades a pending handoff or
  // an unknown masking state into a "safe"/"confirmed" claim on its own.
  const isHumanControlled = isConfirmedHuman(truth);
  const maskingInfo = maskingCopy(truth.masking);
  const handoffPending = isPendingHandoff(truth);
  const takeoverError = truth.handoff === "failed" ? truth.handoffError : null;
  const frameAge = frameAgeMs(truth, now);
  const frameStale = isFrameStale(truth, now);

  useEffect(() => {
    truthRef.current = truth;
  }, [truth]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

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

    const token = (await getBrowserSessionToken()) ?? "";
    let wsUrl: string;
    let wsTicket: string;
    try {
      const res = await fetch(`${getApiBaseUrl()}/viewport/ticket`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        throw new Error(`ticket endpoint returned ${res.status}`);
      }
      const data = await res.json();
      wsTicket = data.ticket;
      wsUrl = toWsUrl(`/ws/viewport/${executionId}`);
    } catch {
      setState("disconnected");
      return;
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
      ws.send(JSON.stringify({ type: "authenticate", ticket: wsTicket }));
      reconnectAttemptsRef.current = 0;
      // Frame sequence numbers are per-connection; drop stale continuity.
      setTruth((t) => resetViewportTruth(t));
      pendingFrameSeqRef.current = null;
      setHasReceivedFrame(false);
      setServerConnectionHop((current) => (current === "first_frame_delivered" ? current : "stream_connected"));
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
              setServerConnectionHop("first_frame_delivered");
            }
          }
          URL.revokeObjectURL(objectUrl);
          const ackSeq = pendingFrameSeqRef.current;
          pendingFrameSeqRef.current = null;
          // Acknowledge only frames we actually painted so the server relay can
          // release its send window (MAX_UNACKED) without lying about delivery.
          if (ackSeq !== null && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "frame_ack", seq: ackSeq }));
            setTruth((t) => markFrameAcked(t, ackSeq));
          }
          framePendingRef.current = false;
        };
        img.onerror = () => {
          URL.revokeObjectURL(objectUrl);
          framePendingRef.current = false;
        };
        img.src = objectUrl;
      } else {
        try {
          const msg = JSON.parse(event.data) as ViewportMessage;

          if (msg.type === "frame") {
            // Header precedes the binary JPEG; record the seq so the paint
            // handler acks exactly the frame it rendered.
            const seq = typeof msg.seq === "number" ? msg.seq : Number(msg.seq);
            pendingFrameSeqRef.current = Number.isFinite(seq) ? seq : null;
            setTruth((t) => applyServerMessage(t, msg));
            if (
              msg.state &&
              !isConfirmedHuman(truthRef.current) &&
              truthRef.current.control !== "paused"
            ) {
              setState(String(msg.state).toLowerCase());
            }
            return;
          }

          if (msg.type === "takeover_granted") {
            // Lease granted while the browser is still quiescing; only the
            // server's later HUMAN_CONTROL confirms the handoff.
            leaseIdRef.current = msg.lease_id || null;
            if (msg.generation) generationRef.current = msg.generation;
            setTruth((t) => applyServerMessage(t, msg));
            onTakeover?.();
            return;
          }

          if (msg.type === "takeover_rejected") {
            setTruth((t) => applyServerMessage(t, msg));
            setTimeout(() => {
              setTruth((t) => (t.handoff === "failed" ? markTakeoverDeclined(t) : t));
            }, 4000);
            return;
          }

          if (msg.type === "control_changed") {
            if (msg.lease_id) leaseIdRef.current = msg.lease_id;
            if (msg.generation) generationRef.current = msg.generation;
            if (msg.checkpoint !== undefined) setCheckpoint(msg.checkpoint);
            setTruth((t) => applyServerMessage(t, msg));
            if (msg.control === "human") {
              setState("user_control");
            } else if (msg.control === "paused" || msg.control === "waiting_user") {
              setState("paused");
            } else if (msg.control === "agent") {
              leaseIdRef.current = null;
              setState("resuming");
              setTimeout(() => setState((s) => (s === "resuming" ? "executing" : s)), 1500);
            }
            return;
          }

          if (msg.type === "state") {
            if (msg.checkpoint !== undefined) setCheckpoint(msg.checkpoint);
            if (msg.state) setState(String(msg.state).toLowerCase());
            if (msg.url) setUrl(msg.url);
            if (msg.title) setTitle(msg.title);
            if (msg.cursor) setCursor(msg.cursor);
            else if (msg.state !== "paused" && msg.state !== "user_control") setCursor(null);
            setTruth((t) => applyServerMessage(t, msg));
            return;
          }

          if (msg.type === "takeover_request") {
            setShowTakeoverDialog(true);
            return;
          }

          if (msg.type === "connection_hop" && msg.hop) {
            setServerConnectionHop(msg.hop);
            return;
          }

          if (msg.type === "load_phase" && msg.phase) {
            setServerLoadPhase(msg.phase);
            return;
          }

          if (msg.type === "pending_request") {
            setServerPendingMessage(msg.message || (msg.host ? `Page loaded; waiting on ${msg.host} (pending ${msg.age_s ?? 0}s)` : null));
            return;
          }

          if (msg.type === "platform_wake") {
            setServerPlatformWakeMessage(msg.message || null);
            return;
          }

          if (msg.type === "progress") {
            if (msg.id === "exp-warmup" && msg.message) {
              setServerPlatformWakeMessage(msg.message);
            } else if (msg.id === "exp-pending-wait" && msg.message) {
              setServerPendingMessage(msg.message);
            }
          }

          // masking_status, connection_quality, control_error,
          // interaction_rejected, pause_requested, resume_requested, lease_expired.
          setTruth((t) => applyServerMessage(t, msg));
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
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "takeover_accept" }));
    }
    setTruth(markTakeoverRequested);
    setShowTakeoverDialog(false);
  }, []);

  const handleTakeoverReject = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "takeover_reject" }));
    }
    setTruth(markTakeoverDeclined);
    setShowTakeoverDialog(false);
    onRelease?.();
  }, [onRelease]);

  const handleReturnControl = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: "return_control",
          lease_id: leaseIdRef.current,
        })
      );
    }
    // Remain in human control until the server confirms the agent resumed;
    // the confirmed control_changed message releases the lease.
    setTruth(markReturnRequested);
    onRelease?.();
  }, [onRelease]);

  const handlePause = useCallback(() => {
    // Optimistic pause/pause UI would lie about a state only the server owns.
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "pause" }));
    }
  }, []);

  const handleResume = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "resume" }));
    }
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

  const config = resolveViewportStateConfig(state);
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
          <div className={cn("h-2 w-2 rounded-full", config?.color || "bg-primary", state === "observing" || state === "executing" || state === "loading" ? "animate-pulse" : "")} />
          <MaterialIcon name={config?.icon || "visibility"} className="h-3.5 w-3.5 text-muted-foreground" />
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
            {activePlatformWakeMessage ? (
              <div className="flex flex-col items-center max-w-sm rounded-xl border border-amber-500/40 bg-amber-500/10 p-5 backdrop-blur-xs text-amber-200">
                <MaterialIcon name="bolt" size={32} className="text-amber-400 mb-2 animate-pulse" />
                <p className="text-body-sm font-semibold text-neutral-100">
                  {activePlatformWakeMessage}
                </p>
                <p className="text-caption text-neutral-300 mt-1 mb-2">
                  Waiting for backend container to finish booting. Exploration will continue automatically.
                </p>
                {activePendingMessage && (
                  <p className="text-caption text-amber-300/80 font-mono mt-1">
                    {activePendingMessage}
                  </p>
                )}
                {onRetry && (
                  <button
                    type="button"
                    onClick={onRetry}
                    className="mt-3 inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 text-xs font-medium border border-amber-500/40 transition-colors cursor-pointer"
                  >
                    <MaterialIcon name="refresh" size={13} />
                    Retry
                  </button>
                )}
              </div>
            ) : activePendingMessage ? (
              <div className="flex flex-col items-center max-w-sm rounded-xl border border-blue-500/40 bg-blue-500/10 p-5 backdrop-blur-xs text-blue-200">
                <MaterialIcon name="hourglass_top" size={32} className="text-blue-400 mb-2 animate-spin" />
                <p className="text-body-sm font-semibold text-neutral-100">
                  {activePendingMessage}
                </p>
                <p className="text-caption text-neutral-300 mt-1">
                  Document received; waiting for pending backend requests to resolve.
                </p>
              </div>
            ) : (
              <>
                <div className="relative mb-3 flex h-14 w-14 items-center justify-center rounded-2xl border border-primary/30 bg-primary/10 shadow-lg">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-2xl bg-primary opacity-20" />
                  <MaterialIcon
                    name={
                      activeHop === "worker_started"
                        ? "memory"
                        : activeHop === "browser_launched"
                        ? "language"
                        : activeHop === "stream_connected"
                        ? "sensors"
                        : "smart_toy"
                    }
                    size={28}
                    className="text-primary animate-pulse"
                  />
                </div>
                <p className="text-body-sm font-medium text-neutral-200">
                  {activeHop === "worker_started"
                    ? "Worker started · Launching browser..."
                    : activeHop === "browser_launched"
                    ? "Browser launched · Connecting stream..."
                    : activeHop === "stream_connected"
                    ? "Stream connected · Waiting for first frame..."
                    : "Connecting · Starting worker..."}
                </p>
                {activeLoadPhase ? (
                  <div className="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-primary/30 bg-primary/5 text-caption font-mono text-primary">
                    <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
                    <span>
                      {activeLoadPhase === "navigation_committed"
                        ? "Navigation committed"
                        : activeLoadPhase === "domcontentloaded"
                        ? "DOMContentLoaded"
                        : activeLoadPhase === "first_contentful_paint"
                        ? "First Contentful Paint"
                        : activeLoadPhase === "dom_settled"
                        ? "DOM settled"
                        : activeLoadPhase}
                    </span>
                  </div>
                ) : (
                  <p className="text-caption text-neutral-400 mt-0.5 max-w-xs">
                    Live viewport frames and interactions will stream here in real time.
                  </p>
                )}
              </>
            )}
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
        <div className="absolute top-2.5 left-2.5 z-20 flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-background/90 backdrop-blur-md border border-border/60 shadow-xs">
          <div className={cn("h-1.5 w-1.5 rounded-full", config?.color || "bg-primary", "animate-pulse")} />
          <span className="text-caption font-medium text-foreground">{config?.label || "Active"}</span>
        </div>

        {/* Measured pending requests or platform wake overlay */}
        {hasReceivedFrame && activePendingMessage && (
          <div className="absolute top-2.5 right-2.5 z-20 flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-blue-500/10 dark:bg-blue-950/60 backdrop-blur-md border border-blue-500/30 text-blue-900 dark:text-blue-200 text-caption font-mono shadow-xs">
            <MaterialIcon name="hourglass_top" size={13} className="text-blue-600 dark:text-blue-400 animate-spin shrink-0" />
            <span className="font-medium">{activePendingMessage}</span>
          </div>
        )}
        {hasReceivedFrame && activePlatformWakeMessage && !activePendingMessage && (
          <div className="absolute top-2.5 right-2.5 z-20 flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-amber-500/10 dark:bg-amber-950/60 backdrop-blur-md border border-amber-500/30 text-amber-900 dark:text-amber-200 text-caption shadow-xs">
            <MaterialIcon name="bolt" size={13} className="text-amber-600 dark:text-amber-400 animate-pulse shrink-0" />
            <span className="font-medium">{activePlatformWakeMessage}</span>
          </div>
        )}

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
          <div className="absolute top-10 left-3 right-3 z-30 flex items-center justify-between gap-3 p-3 rounded-lg bg-card/95 border border-amber-500/40 text-foreground backdrop-blur-md shadow-lg animate-in fade-in slide-in-from-top-2 duration-200">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-8 h-8 rounded-full bg-amber-500/15 border border-amber-500/30 flex items-center justify-center shrink-0">
                <MaterialIcon name="security" className="w-4 h-4 text-amber-600 dark:text-amber-400" />
              </div>
              <div className="text-xs min-w-0">
                <p className="font-semibold text-amber-900 dark:text-amber-200">Verification Barrier Encountered</p>
                <p className="text-muted-foreground truncate">{checkpoint.description || "Human intervention required"}</p>
              </div>
            </div>
            {!isHumanControlled ? (
              <button
                type="button"
                onClick={handleTakeoverAccept}
                className="px-3 py-1.5 bg-amber-600 hover:bg-amber-700 text-white font-medium text-xs rounded-md shrink-0 transition-colors shadow-xs cursor-pointer"
              >
                Solve in Browser
              </button>
            ) : (
              <span className="text-[11px] font-mono text-amber-800 dark:text-amber-300 px-2.5 py-1 rounded-md border border-amber-500/30 bg-amber-500/10">
                Solving Challenge...
              </span>
            )}
          </div>
        )}

        {/* Server-confirmed handoff in progress (not yet human control) */}
        {handoffPending && !checkpoint && (
          <div className="absolute top-2.5 inset-x-0 mx-auto w-fit z-20 flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-background/95 border border-border text-caption font-medium text-foreground backdrop-blur-md shadow-md animate-in fade-in duration-200">
            <MaterialIcon name="sync" size={14} className="animate-spin text-primary shrink-0" />
            <span>Confirming control handoff with server…</span>
          </div>
        )}

        {/* Masking honesty: only a server "masked" tag may claim protection */}
        {hasReceivedFrame && maskingInfo.tone !== "protected" && (
          <div
            className={cn(
              "absolute bottom-2.5 left-2.5 z-20 flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-caption font-medium backdrop-blur-md shadow-xs transition-all",
              maskingInfo.tone === "exposed"
                ? "bg-destructive/15 border-destructive/40 text-destructive dark:text-red-300"
                : "bg-amber-500/15 dark:bg-amber-950/70 border-amber-500/40 text-amber-900 dark:text-amber-200"
            )}
          >
            <MaterialIcon
              name={maskingInfo.tone === "exposed" ? "visibility" : "help_outline"}
              size={13}
              className={maskingInfo.tone === "exposed" ? "text-destructive dark:text-red-300" : "text-amber-700 dark:text-amber-400"}
            />
            <span>{maskingInfo.label}</span>
          </div>
        )}

        {/* Stale-frame overlay: the last painted frame is old */}
        {hasReceivedFrame && frameStale && state !== "disconnected" && state !== "failed" && (
          <div className="absolute top-2.5 inset-x-0 mx-auto w-fit z-20 flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-500/15 dark:bg-amber-950/80 border border-amber-500/40 text-amber-900 dark:text-amber-200 text-caption font-medium shadow-md backdrop-blur-md pointer-events-none animate-in fade-in duration-200">
            <MaterialIcon name="sync" size={13} className="text-amber-600 dark:text-amber-400 animate-spin shrink-0" />
            <span>Frame is {Math.round((frameAge ?? 0) / 1000)}s old — waiting for browser</span>
          </div>
        )}

        {/* Takeover error notification */}
        {takeoverError && (
          <div className="absolute top-2.5 right-2.5 z-30 flex items-center gap-2 max-w-sm px-3 py-1.5 rounded-md bg-destructive/15 dark:bg-destructive/25 border border-destructive/40 text-destructive dark:text-red-300 text-xs font-medium shadow-md backdrop-blur-md animate-in fade-in slide-in-from-top-1 duration-200">
            <MaterialIcon name="error_outline" size={14} className="shrink-0 text-destructive dark:text-red-300" />
            <span className="truncate flex-1">{takeoverError}</span>
            <button
              type="button"
              onClick={() => setTruth((t) => ({ ...t, handoffError: null }))}
              className="ml-1 text-destructive/70 hover:text-destructive dark:text-red-300/70 dark:hover:text-red-200 shrink-0 cursor-pointer"
              aria-label="Dismiss notification"
            >
              <MaterialIcon name="close" size={12} />
            </button>
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
          {hasReceivedFrame && state !== "disconnected" && state !== "failed" && (
            <span className="hidden sm:inline text-[11px] font-mono text-muted-foreground/60 shrink-0">
              {truth.quality.fps !== null ? `${truth.quality.fps}fps` : "—"}
              {truth.quality.rttMs !== null ? ` · ${truth.quality.rttMs}ms` : ""}
              {frameAge !== null ? ` · ${Math.round(frameAge / 1000)}s` : ""}
            </span>
          )}
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

